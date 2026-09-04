from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.services import outreach_delivery


def _uses_fallback(settings: Settings) -> bool:
    return outreach_delivery._uses_fallback(settings)


def _client(settings: Settings):
    return outreach_delivery._client(settings)


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass

    return datetime.min.replace(tzinfo=UTC)


def _serialize_time(value: Any) -> str | None:
    if value is None:
        return None

    parsed = _parse_time(value)

    if parsed == datetime.min.replace(tzinfo=UTC):
        return str(value)

    return (
        parsed.isoformat()
        .replace("+00:00", "Z")
    )


def _event_label(event_type: str) -> str:
    labels = {
        "outreach_generated": "Outreach generated",
        "outreach_regenerated": "Outreach regenerated",
        "outreach_edited": "Outreach edited",
        "outreach_saved": "Outreach saved",
        "outreach_approved": "Outreach approved",
        "outreach_send_attempted": "Send attempted",
        "outreach_send_failed": "Send failed",
        "outreach_sent": "Outreach sent",
        "reply_received": "Reply received",
        "inbound_reply_received": "Reply received",
        "sequence_started": "Sequence started",
        "sequence_paused": "Sequence paused",
        "sequence_resumed": "Sequence resumed",
        "sequence_completed": "Sequence completed",
        "sequence_stopped": "Sequence stopped",
        "followup_sent": "Follow-up sent",
        "suppression_added": "Suppression added",
        "crm_sync_started": "CRM sync started",
        "crm_sync_succeeded": "CRM sync succeeded",
        "crm_sync_failed": "CRM sync failed",
    }

    return labels.get(
        event_type,
        event_type.replace("_", " ").strip().title(),
    )


def _timeline_item(
    *,
    item_id: str,
    event_type: str,
    occurred_at: Any,
    payload: dict[str, Any] | None = None,
    source: str,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "event_type": event_type,
        "label": _event_label(event_type),
        "occurred_at": _serialize_time(occurred_at),
        "payload": deepcopy(payload or {}),
        "source": source,
    }


def _fallback_context(
    settings: Settings,
    lead_id: str,
) -> dict[str, Any]:
    state = outreach_delivery._context(
        settings,
        lead_id,
    )

    return state


def _fallback_timeline(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> list[dict[str, Any]]:
    state = _fallback_context(
        settings,
        lead_id,
    )

    lead = state["lead"]

    outreach_delivery._assert_access(
        lead,
        actor_id,
        role,
    )

    raw_state = state["_raw_state"]
    timeline: list[dict[str, Any]] = []

    for event in raw_state.get("events", []):
        timeline.append(
            _timeline_item(
                item_id=str(event.get("id", "")),
                event_type=str(
                    event.get(
                        "event_type",
                        "unknown_event",
                    )
                ),
                occurred_at=(
                    event.get("occurred_at")
                    or event.get("created_at")
                ),
                payload=event.get("event_payload")
                or event.get("payload")
                or {},
                source="outreach_event",
            )
        )

    for reply in raw_state.get(
        "inbound_reply_events",
        [],
    ):
        if str(reply.get("lead_id")) != str(lead_id):
            continue

        timeline.append(
            _timeline_item(
                item_id=str(reply.get("id", "")),
                event_type="reply_received",
                occurred_at=reply.get(
                    "received_at"
                ),
                payload={
                    "classification": reply.get(
                        "classification"
                    ),
                    "is_unsubscribe": bool(
                        reply.get(
                            "is_unsubscribe",
                            False,
                        )
                    ),
                    "from_email": reply.get(
                        "from_email"
                    ),
                    "subject": reply.get(
                        "subject"
                    ),
                },
                source="inbound_reply",
            )
        )

    crm_states = raw_state.get(
        "crm_sync_states",
        {},
    )

    for crm_state in crm_states.values():
        if (
            str(crm_state.get("lead_id"))
            != str(lead_id)
        ):
            continue

        status = str(
            crm_state.get(
                "sync_status",
                "pending",
            )
        )

        timeline.append(
            _timeline_item(
                item_id=str(
                    crm_state.get("id", "")
                ),
                event_type=f"crm_state_{status}",
                occurred_at=(
                    crm_state.get("synced_at")
                    or crm_state.get(
                        "updated_at"
                    )
                    or crm_state.get(
                        "created_at"
                    )
                ),
                payload={
                    "provider_key": (
                        crm_state.get(
                            "provider_key"
                        )
                    ),
                    "external_crm_id": (
                        crm_state.get(
                            "external_crm_id"
                        )
                    ),
                    "error_message": (
                        crm_state.get(
                            "error_message"
                        )
                    ),
                },
                source="crm_state",
            )
        )

    timeline.sort(
        key=lambda item: _parse_time(
            item.get("occurred_at")
        ),
        reverse=True,
    )

    return timeline


def _db_lead(
    settings: Settings,
    lead_id: str,
) -> dict[str, Any]:
    rows = (
        _client(settings)
        .table("leads")
        .select("*")
        .eq("id", lead_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not rows:
        raise ValueError("Lead not found")

    return rows[0]


def _db_outreach(
    settings: Settings,
    lead_id: str,
) -> dict[str, Any] | None:
    rows = (
        _client(settings)
        .table("lead_outreach")
        .select("*")
        .eq("lead_id", lead_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    return rows[0] if rows else None


def _db_timeline(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> list[dict[str, Any]]:
    lead = _db_lead(
        settings,
        lead_id,
    )

    outreach_delivery._assert_access(
        lead,
        actor_id,
        role,
    )

    outreach = _db_outreach(
        settings,
        lead_id,
    )

    timeline: list[dict[str, Any]] = []

    if outreach:
        event_rows = (
            _client(settings)
            .table("outreach_events")
            .select("*")
            .eq(
                "lead_outreach_id",
                outreach["id"],
            )
            .execute()
            .data
            or []
        )

        for event in event_rows:
            timeline.append(
                _timeline_item(
                    item_id=str(
                        event.get("id", "")
                    ),
                    event_type=str(
                        event.get(
                            "event_type",
                            "unknown_event",
                        )
                    ),
                    occurred_at=event.get(
                        "occurred_at"
                    ),
                    payload=event.get(
                        "event_payload"
                    )
                    or {},
                    source="outreach_event",
                )
            )

    reply_rows = (
        _client(settings)
        .table("inbound_reply_events")
        .select("*")
        .eq("lead_id", lead_id)
        .execute()
        .data
        or []
    )

    for reply in reply_rows:
        timeline.append(
            _timeline_item(
                item_id=str(
                    reply.get("id", "")
                ),
                event_type="reply_received",
                occurred_at=reply.get(
                    "received_at"
                ),
                payload={
                    "classification": reply.get(
                        "classification"
                    ),
                    "is_unsubscribe": bool(
                        reply.get(
                            "is_unsubscribe",
                            False,
                        )
                    ),
                    "from_email": reply.get(
                        "from_email"
                    ),
                    "subject": reply.get(
                        "subject"
                    ),
                },
                source="inbound_reply",
            )
        )

    crm_rows = (
        _client(settings)
        .table("crm_sync_state")
        .select("*")
        .eq("lead_id", lead_id)
        .execute()
        .data
        or []
    )

    for crm_state in crm_rows:
        status = str(
            crm_state.get(
                "sync_status",
                "pending",
            )
        )

        timeline.append(
            _timeline_item(
                item_id=str(
                    crm_state.get("id", "")
                ),
                event_type=f"crm_state_{status}",
                occurred_at=(
                    crm_state.get("synced_at")
                    or crm_state.get(
                        "updated_at"
                    )
                    or crm_state.get(
                        "created_at"
                    )
                ),
                payload={
                    "provider_key": (
                        crm_state.get(
                            "provider_key"
                        )
                    ),
                    "external_crm_id": (
                        crm_state.get(
                            "external_crm_id"
                        )
                    ),
                    "error_message": (
                        crm_state.get(
                            "error_message"
                        )
                    ),
                },
                source="crm_state",
            )
        )

    timeline.sort(
        key=lambda item: _parse_time(
            item.get("occurred_at")
        ),
        reverse=True,
    )

    return timeline


def get_lead_outreach_timeline(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> list[dict[str, Any]]:
    if _uses_fallback(settings):
        return _fallback_timeline(
            settings,
            actor_id,
            role,
            lead_id,
        )

    return _db_timeline(
        settings,
        actor_id,
        role,
        lead_id,
    )


def _metrics_from_timeline(
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    event_counts = Counter(
        item["event_type"]
        for item in timeline
    )

    replies = [
        item
        for item in timeline
        if item["source"] == "inbound_reply"
    ]

    reply_classifications = Counter(
        str(
            item.get("payload", {}).get(
                "classification"
            )
            or "unknown"
        )
        for item in replies
    )

    sent_count = event_counts.get(
        "outreach_sent",
        0,
    ) + event_counts.get(
        "followup_sent",
        0,
    )

    replied_count = len(replies)

    reply_rate = (
        replied_count / sent_count
        if sent_count > 0
        else 0.0
    )

    crm_synced = sum(
        1
        for item in timeline
        if (
            item["event_type"]
            == "crm_state_synced"
        )
    )

    crm_failed = sum(
        1
        for item in timeline
        if (
            item["event_type"]
            == "crm_state_failed"
        )
    )

    unsubscribe_count = sum(
        1
        for item in replies
        if bool(
            item.get("payload", {}).get(
                "is_unsubscribe"
            )
        )
    )

    return {
        "sent_count": sent_count,
        "reply_count": replied_count,
        "reply_rate": round(
            reply_rate,
            4,
        ),
        "interested_count": (
            reply_classifications.get(
                "interested",
                0,
            )
        ),
        "meeting_request_count": (
            reply_classifications.get(
                "meeting_request",
                0,
            )
        ),
        "not_interested_count": (
            reply_classifications.get(
                "not_interested",
                0,
            )
        ),
        "unsubscribe_count": (
            unsubscribe_count
        ),
        "crm_synced_count": crm_synced,
        "crm_failed_count": crm_failed,
        "event_counts": dict(
            sorted(event_counts.items())
        ),
        "reply_classifications": dict(
            sorted(
                reply_classifications.items()
            )
        ),
    }


def get_lead_outreach_analytics(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> dict[str, Any]:
    timeline = get_lead_outreach_timeline(
        settings,
        actor_id,
        role,
        lead_id,
    )

    return {
        "lead_id": lead_id,
        "metrics": _metrics_from_timeline(
            timeline
        ),
        "timeline_count": len(timeline),
    }
