from __future__ import annotations

from dataclasses import dataclass

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
    score_discovered_prospects,
)


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

    discovery = discover_from_active_icp(
        prospect_client,
        size=requested_limit,
        page_size=min(page_size or requested_limit, requested_limit),
        page=page,
    )

    scored = score_discovered_prospects(
        discovery.prospects
    )

    intelligence = enrich_qualified_with_events(
        scored,
        events_client,
        timestamp_from=timestamp_from,
        warnings=warnings,
    )

    persistence = (
        persist_discovery_intelligence(
            supabase_client,
            intelligence,
        )
    )

    return DiscoveryCycleResult(
        requested_limit=requested_limit,
        fetched_count=len(discovery.prospects),
        stored_count=persistence.stored_count,
        duplicate_count=persistence.duplicate_count,
        qualified_count=len(scored.qualified),
        review_count=len(scored.needs_review),
        rejected_count=len(scored.rejected),
        evidence_count=persistence.evidence_count,
        draft_count=persistence.draft_count,
        errors=persistence.errors,
        warnings=warnings,
    )
