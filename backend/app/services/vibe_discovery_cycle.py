from __future__ import annotations

from dataclasses import dataclass
import logging

from app.core.config import get_settings
from app.integrations.vibe.client import VibeProspectingClient
from app.integrations.vibe.events import VibeEventsClient
from app.services.qualified_event_intelligence import (
    enrich_qualified_with_events,
)
from app.services.vibe_discovery import (
    discover_from_active_icp,
)
from app.services.vibe_discovery_persistence import (
    persist_discovery_intelligence,
)
from app.services.vibe_icp_pipeline import (
    ScoredDiscoveryBatch,
    score_discovered_prospects,
)
from app.services.vibe_prefilter import prefilter_prospect


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveryCycleResult:
    requested_limit: int
    fetched_count: int
    stored_count: int
    duplicate_count: int
    qualified_count: int
    review_count: int
    rejected_count: int
    evidence_count: int
    draft_count: int
    errors: list[str]
    warnings: list[str]


def approved_daily_limit(
    requested: int | None,
    configured: int,
    *,
    allow_over_cap: bool = False,
) -> int:
    if configured < 1:
        raise ValueError("DAILY_VIBE_LEAD_LIMIT must be at least one")
    if configured > 100 and not allow_over_cap:
        raise ValueError(
            "DAILY_VIBE_LEAD_LIMIT above 100 requires "
            "VIBE_ALLOW_OVER_DAILY_CAP=true"
        )

    limit = configured if requested is None else requested
    if limit < 1:
        raise ValueError("Discovery limit must be at least one")
    if limit > configured:
        raise ValueError(
            f"Requested discovery limit {limit} exceeds "
            f"DAILY_VIBE_LEAD_LIMIT={configured}"
        )
    if limit > 100 and not allow_over_cap:
        raise ValueError("A daily discovery run is capped at 100 leads")
    return limit


def run_vibe_discovery_cycle(
    supabase_client,
    *,
    size: int = 100,
    page_size: int | None = None,
    page: int = 1,
    timestamp_from: str | None = None,
) -> DiscoveryCycleResult:
    settings = get_settings()

    if not settings.vibe_api_key:
        raise RuntimeError(
            "VIBE_API_KEY is required"
        )

    prospect_client = VibeProspectingClient(
        settings.vibe_api_key,
        settings.vibe_api_base_url,
    )

    events_client = VibeEventsClient(
        settings.vibe_api_key,
        settings.vibe_api_base_url,
    )

    requested_limit = approved_daily_limit(
        size,
        settings.daily_vibe_lead_limit,
        allow_over_cap=settings.vibe_allow_over_daily_cap,
    )
    warnings: list[str] = []

    # The cap counts newly stored candidates, not broad provider rows. Keep the
    # search bounded even when Vibe returns only rejects or existing identities.
    stored = duplicates = fetched = qualified = review = rejected = evidence = drafts = 0
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    candidate_budget = requested_limit * 10
    current_page = page
    country_code = "US"
    country_fetched = 0
    provider_page_size = min(page_size or requested_limit, requested_limit, 100)
    while fetched < candidate_budget and stored < requested_limit:
        discovery = discover_from_active_icp(
            prospect_client,
            size=candidate_budget,
            page_size=provider_page_size,
            page=current_page,
            country_code=country_code,
        )
        if not discovery.prospects:
            if country_code == "US":
                country_code, current_page, country_fetched = "AE", page, 0
                continue
            break
        candidates = []
        for prospect in discovery.prospects:
            fetched += 1
            country_fetched += 1
            identities = {
                (key, str(prospect[key]).strip().rstrip("/").casefold())
                for key in ("vibe_prospect_id", "vibe_business_id", "linkedin_url", "company_url", "email")
                if prospect.get(key)
            }
            if identities & seen:
                duplicates += 1
                continue
            # A rejected contact must not hide a later valid buyer at the same company.
            if prefilter_prospect(prospect).accepted:
                seen.update(identities)
            candidates.append(prospect)
        scored = score_discovered_prospects(candidates)
        rejected += len(scored.rejected)
        for index, item in enumerate(scored.rejected, start=1):
            message = (
                f"Rejected prospect on page {current_page}, rejection {index}: "
                + "; ".join(item.score.hard_stops)
            )
            warnings.append(message)
            logger.info(message)
        remaining = requested_limit - stored
        accepted_qualified = scored.qualified[:remaining]
        accepted_review = scored.needs_review[:remaining - len(accepted_qualified)]
        scored = ScoredDiscoveryBatch(accepted_qualified, accepted_review, [])
        qualified += len(scored.qualified)
        review += len(scored.needs_review)
        intelligence = enrich_qualified_with_events(
            scored, events_client, timestamp_from=timestamp_from, warnings=warnings,
        )
        persistence = persist_discovery_intelligence(supabase_client, intelligence)
        stored += persistence.stored_count
        duplicates += persistence.duplicate_count
        evidence += persistence.evidence_count
        drafts += persistence.draft_count
        errors.extend(persistence.errors)
        if errors:
            break
        if current_page >= discovery.total_pages or (
            country_code == "US" and country_fetched >= requested_limit * 8
        ):
            if country_code == "US":
                country_code, current_page, country_fetched = "AE", page, 0
                continue
            break
        current_page += 1
    if stored < requested_limit:
        warnings.append(
            f"Stored {stored} of {requested_limit} requested ICP candidates; "
            "provider results or bounded search exhausted. Fit rules were not relaxed."
        )
    return DiscoveryCycleResult(
        requested_limit=requested_limit,
        fetched_count=fetched,
        stored_count=stored,
        duplicate_count=duplicates,
        qualified_count=qualified,
        review_count=review,
        rejected_count=rejected,
        evidence_count=evidence,
        draft_count=drafts,
        errors=errors,
        warnings=warnings,
    )
