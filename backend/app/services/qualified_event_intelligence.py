from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.integrations.vibe.events import (
    VibeBusinessEvent,
    VibeEventsClient,
)
from app.intent import IntentEngine, IntentScore
from app.services.vibe_event_intent import (
    business_events_to_evidence,
)
from app.services.vibe_icp_pipeline import (
    ScoredDiscoveryBatch,
    ScoredProspect,
)


@dataclass(frozen=True)
class QualifiedProspectIntelligence:
    scored_prospect: ScoredProspect
    business_id: str | None
    events: list[VibeBusinessEvent] = field(
        default_factory=list
    )
    evidence: list[dict[str, Any]] = field(
        default_factory=list
    )
    intent: IntentScore = field(
        default_factory=lambda: IntentScore(
            score=0,
            level="low",
            reasons=[],
            evidence_urls=[],
        )
    )


def _business_id(
    prospect: dict[str, Any],
) -> str | None:
    value = (
        prospect.get("vibe_business_id")
        or prospect.get("business_id")
    )

    if not isinstance(value, str):
        return None

    value = value.strip()

    return value or None


def _prospect_evidence(
    prospect: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_items = prospect.get("evidence")

    if not isinstance(raw_items, list):
        return []

    allowed_types = {
        "linkedin_post",
        "linkedin_comment",
        "linkedin_activity",
        "company_page",
        "job_page",
        "news",
        "search_result",
        "other",
    }
    evidence: list[dict[str, Any]] = []

    for raw in raw_items:
        if not isinstance(raw, dict):
            continue

        title = raw.get("title")
        source_url = raw.get("source_url")

        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(source_url, str) or not source_url.strip():
            continue

        source_url = source_url.strip()
        parsed = urlparse(source_url)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            continue

        evidence_type = str(raw.get("evidence_type") or "other")
        if evidence_type == "job_post":
            evidence_type = "job_page"
        if evidence_type not in allowed_types:
            evidence_type = "other"

        supports_fields = raw.get("supports_fields")
        evidence.append(
            {
                "evidence_type": evidence_type,
                "title": title.strip(),
                "source_url": source_url,
                "publisher": raw.get("publisher") or "Explorium AgentSource",
                "excerpt": raw.get("excerpt"),
                "published_at": raw.get("published_at"),
                "activity_at": raw.get("activity_at"),
                "intent_signal": raw.get("intent_signal"),
                "intent_reason": raw.get("intent_reason"),
                "intent_score_delta": raw.get("intent_score_delta"),
                "supports_fields": supports_fields if isinstance(supports_fields, list) else [],
                "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            }
        )

    return evidence


def _merge_evidence(
    *collections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for collection in collections:
        for item in collection:
            source_url = str(item.get("source_url") or "").strip()
            if not source_url:
                continue
            key = source_url.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    return merged


def enrich_qualified_with_events(
    batch: ScoredDiscoveryBatch,
    client: VibeEventsClient,
    *,
    timestamp_from: str | None = None,
    warnings: list[str] | None = None,
) -> list[QualifiedProspectIntelligence]:
    scored_prospects = [
        *batch.qualified,
        *batch.needs_review,
    ]

    if not scored_prospects:
        return []

    ids: list[str] = []

    for item in scored_prospects:
        business_id = _business_id(
            item.prospect
        )

        if (
            business_id
            and business_id not in ids
        ):
            ids.append(business_id)

    event_map: dict[
        str,
        list[VibeBusinessEvent],
    ] = {}

    for start in range(0, len(ids), 40):
        chunk = ids[start:start + 40]

        try:
            events = client.fetch_business_events(
                chunk,
                timestamp_from=timestamp_from,
            )
        except Exception as exc:
            if warnings is not None:
                warnings.append(
                    "Vibe event lookup failed for a business batch: "
                    f"{type(exc).__name__}"
                )
            continue

        for event in events:
            if not event.business_id:
                continue

            event_map.setdefault(
                event.business_id,
                [],
            ).append(event)

    results: list[
        QualifiedProspectIntelligence
    ] = []

    for scored in scored_prospects:
        business_id = _business_id(
            scored.prospect
        )

        events = (
            event_map.get(
                business_id,
                [],
            )
            if business_id
            else []
        )

        evidence = _merge_evidence(
            _prospect_evidence(scored.prospect),
            business_events_to_evidence(events),
        )

        intent = IntentEngine.score(
            scored.prospect,
            evidence,
        )

        results.append(
            QualifiedProspectIntelligence(
                scored_prospect=scored,
                business_id=business_id,
                events=events,
                evidence=evidence,
                intent=intent,
            )
        )

    return results
