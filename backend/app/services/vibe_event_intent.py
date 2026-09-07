from __future__ import annotations

from typing import Any

from app.integrations.vibe.events import VibeBusinessEvent


def _event_signal(
    event_type: str,
    text: str,
) -> tuple[str | None, str | None, int | None]:
    haystack = f"{event_type} {text}".casefold()

    rules = [
        (
            ("funding", "funded", "investment", "raise"),
            "funding",
            "Recent funding may increase budget and capacity for software initiatives.",
            20,
        ),
        (
            ("hiring", "hire", "headcount", "recruit", "job posting", "open role"),
            "hiring",
            "Hiring activity indicates active company growth or capability expansion.",
            15,
        ),
        (
            ("launch", "product release", "new product"),
            "product_launch",
            "A recent product launch may create new engineering, integration, or scaling needs.",
            15,
        ),
        (
            ("expand", "expansion", "new market", "new office"),
            "expansion",
            "Business expansion can create demand for new systems, integrations, and operational automation.",
            15,
        ),
        (
            ("partnership", "partner"),
            "partnership",
            "New partnership activity may create integration or delivery requirements.",
            10,
        ),
        (
            ("ai", "artificial intelligence", "automation"),
            "ai_automation",
            "Recent AI or automation activity indicates active interest in technology investment.",
            20,
        ),
        (
            ("technology", "software", "data platform", "data infrastructure"),
            "software_need",
            "Public technology activity indicates a possible software or data initiative.",
            15,
        ),
        (
            ("website", "web platform", "mobile app", "mobile application"),
            "digital_product",
            "Public digital product activity indicates potential website or mobile delivery needs.",
            15,
        ),
        (
            ("crm", "customer relationship"),
            "crm_interest",
            "CRM-related activity indicates possible sales or operational system needs.",
            15,
        ),
        (
            ("revenue growth", "revenue increase", "grew revenue", "growth"),
            "growth",
            "Public growth activity may indicate expanding operational and software needs.",
            15,
        ),
        (
            ("acquisition", "acquired", "merger", "m&a"),
            "ma_activity",
            "M&A activity can create integration, migration, and operational technology requirements.",
            15,
        ),
    ]

    for keywords, signal, reason, delta in rules:
        if any(keyword in haystack for keyword in keywords):
            return signal, reason, delta

    return None, None, None


def business_event_to_evidence(
    event: VibeBusinessEvent,
) -> dict[str, Any] | None:
    if not event.source_url:
        return None

    searchable_text = " ".join(
        part
        for part in [
            event.title,
            event.excerpt or "",
        ]
        if part
    )

    signal, reason, delta = _event_signal(
        event.event_type,
        searchable_text,
    )

    supports_fields = ["company_activity"]

    if signal:
        supports_fields.append("intent")

    evidence_type = "other"
    if signal == "hiring":
        evidence_type = "job_page"
    elif signal in {"funding", "growth", "ma_activity", "expansion", "product_launch"}:
        evidence_type = "news"

    return {
        "evidence_type": evidence_type,
        "title": event.title,
        "source_url": event.source_url,
        "publisher": "Explorium AgentSource",
        "excerpt": event.excerpt,
        "published_at": event.occurred_at,
        "activity_at": event.occurred_at,
        "intent_signal": signal,
        "intent_reason": reason,
        "intent_score_delta": delta,
        "supports_fields": supports_fields,
        "metadata": {
            "provider": "agentsource",
            "event_id": event.event_id,
            "event_type": event.event_type,
        },
    }


def business_events_to_evidence(
    events: list[VibeBusinessEvent],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()

    for event in events:
        item = business_event_to_evidence(event)

        if item is None:
            continue

        key = item["source_url"].casefold()

        if key in seen:
            continue

        seen.add(key)
        evidence.append(item)

    return evidence
