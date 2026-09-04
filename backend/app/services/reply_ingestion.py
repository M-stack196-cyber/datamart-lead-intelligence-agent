from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.integrations.outbound import InboundReplyRequest
from app.schemas.outbound import ReplyClassification
from app.services import outreach_delivery, outreach_generation


def _now() -> str:
    return (
        datetime.now(tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _iso(value: datetime) -> str:
    return (
        value.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _uses_fallback(settings: Settings) -> bool:
    return outreach_delivery._uses_fallback(settings)


def _client(settings: Settings):
    return outreach_delivery._client(settings)


def classify_reply(
    subject: str,
    body: str,
) -> tuple[ReplyClassification, str, bool]:
    text = f"{subject}\n{body}".strip().casefold()

    unsubscribe_patterns = (
        r"\bunsubscribe\b",
        r"\bremove me\b",
        r"\bstop (?:emailing|contacting) me\b",
        r"\bdo not (?:email|contact) me\b",
        r"\bdon't (?:email|contact) me\b",
        r"\bopt me out\b",
    )
    if any(re.search(pattern, text) for pattern in unsubscribe_patterns):
        return (
            ReplyClassification.UNSUBSCRIBE,
            "Reply contains an explicit opt-out request",
            True,
        )

    out_of_office_patterns = (
        r"\bout of office\b",
        r"\bautomatic reply\b",
        r"\bauto[- ]?reply\b",
        r"\bcurrently away\b",
        r"\bon leave\b",
    )
    if any(re.search(pattern, text) for pattern in out_of_office_patterns):
        return (
            ReplyClassification.OUT_OF_OFFICE,
            "Reply appears to be an automatic out-of-office response",
            False,
        )

    not_interested_patterns = (
        r"\bnot interested\b",
        r"\bno thanks\b",
        r"\bno thank you\b",
        r"\bnot a fit\b",
        r"\bnot relevant\b",
        r"\bpass on this\b",
    )
    if any(re.search(pattern, text) for pattern in not_interested_patterns):
        return (
            ReplyClassification.NOT_INTERESTED,
            "Reply explicitly declines the outreach",
            False,
        )

    meeting_patterns = (
        r"\bschedule (?:a )?(?:call|meeting)\b",
        r"\bbook (?:a )?(?:call|meeting|time)\b",
        r"\bcalendar\b",
        r"\bmeet next week\b",
        r"\bcall next week\b",
        r"\bset up (?:a )?(?:call|meeting)\b",
    )
    if any(re.search(pattern, text) for pattern in meeting_patterns):
        return (
            ReplyClassification.MEETING_REQUEST,
            "Reply requests or proposes a meeting",
            False,
        )

    interested_patterns = (
        r"\bi(?:'m| am) interested\b",
        r"\binterested\b",
        r"\bsounds good\b",
        r"\bhappy to discuss\b",
        r"\blet'?s talk\b",
        r"\btell me more\b",
    )
    if any(re.search(pattern, text) for pattern in interested_patterns):
        return (
            ReplyClassification.INTERESTED,
            "Reply expresses positive interest",
            False,
        )

    objection_patterns = (
        r"\btoo expensive\b",
        r"\bbudget\b",
        r"\balready (?:use|using|have)\b",
        r"\bnot (?:the )?right time\b",
        r"\bnot now\b",
        r"\btiming\b",
    )
    if any(re.search(pattern, text) for pattern in objection_patterns):
        return (
            ReplyClassification.OBJECTION,
            "Reply contains a commercial or timing objection",
            False,
        )

    if "?" in body:
        return (
            ReplyClassification.QUESTION,
            "Reply contains a direct question",
            False,
        )

    return (
        ReplyClassification.UNKNOWN,
        "No deterministic reply category matched",
        False,
    )


def _dedupe_key(request: InboundReplyRequest) -> str:
    provider = request.provider_name.strip().casefold()

    if request.provider_message_id:
        material = (
            "provider-message|"
            + provider
            + "|"
            + request.provider_message_id.strip()
        )
    else:
        material = "|".join(
            [
                "reply",
                provider,
                request.lead_id,
                request.lead_outreach_id,
                request.from_email.strip().casefold(),
                _iso(request.received_at),
                request.subject.strip(),
                request.body.strip(),
            ]
        )

    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _assert_request_matches_context(
    request: InboundReplyRequest,
    state: dict[str, Any],
    actor_id: str,
    role: str,
) -> str:
    lead = state["lead"]
    outreach = state["lead_outreach"]

    outreach_delivery._assert_access(
        lead,
        actor_id,
        role,
    )

    if str(outreach["id"]) != str(request.lead_outreach_id):
        raise ValueError(
            "Reply outreach record does not match the lead"
        )

    expected_email = outreach_delivery._normalize_recipient(
        str(lead.get("email") or "").strip()
    )

    sender_email = outreach_delivery._normalize_recipient(
        request.from_email.strip()
    )

    if sender_email.casefold() != expected_email.casefold():
        raise ValueError(
            "Reply sender does not match the lead email"
        )

    return sender_email


def _fallback_messages(
    raw_state: dict[str, Any],
) -> list[dict[str, Any]]:
    messages = raw_state.get("messages")

    if messages is None:
        latest = raw_state.get("latest_message")
        messages = [latest] if latest else []
        raw_state["messages"] = messages

    return messages


def _fallback_existing_reply(
    raw_state: dict[str, Any],
    dedupe_key: str,
) -> dict[str, Any] | None:
    for reply in raw_state.get("inbound_replies", []):
        if reply.get("dedupe_key") == dedupe_key:
            return reply

    return None


def _serialize_reply(
    reply: dict[str, Any],
    *,
    idempotent: bool,
) -> dict[str, Any]:
    return {
        **deepcopy(reply),
        "idempotent": idempotent,
    }


def _fallback_ingest(
    settings: Settings,
    actor_id: str,
    role: str,
    request: InboundReplyRequest,
) -> dict[str, Any]:
    state = outreach_delivery._context(
        settings,
        request.lead_id,
    )

    sender_email = _assert_request_matches_context(
        request,
        state,
        actor_id,
        role,
    )

    raw_state = state["_raw_state"]
    dedupe_key = _dedupe_key(request)

    existing = _fallback_existing_reply(
        raw_state,
        dedupe_key,
    )
    if existing:
        return _serialize_reply(
            existing,
            idempotent=True,
        )

    (
        classification,
        classification_reason,
        is_unsubscribe,
    ) = classify_reply(
        request.subject,
        request.body,
    )

    received_at = _iso(request.received_at)
    outreach = state["lead_outreach"]
    message_id = "message-" + uuid4().hex

    message = {
        "id": message_id,
        "lead_outreach_id": outreach["id"],
        "sequence_step_id": None,
        "step_number": outreach.get("current_step_number"),
        "direction": "inbound",
        "status": "replied",
        "subject": request.subject.strip(),
        "body": request.body.strip(),
        "generation_provider": request.provider_name,
        "generation_model": None,
        "provider_message_id": request.provider_message_id,
        "idempotency_key": "reply-" + dedupe_key,
        "error_message": None,
        "provider_response": {
            "thread_id": request.thread_id,
            "metadata": request.metadata,
            "classification": classification.value,
        },
        "generated_at": received_at,
        "approved_at": None,
        "approved_by": None,
        "scheduled_at": None,
        "sent_at": None,
        "replied_at": received_at,
        "created_by": actor_id,
        "updated_by": actor_id,
        "created_at": received_at,
        "updated_at": received_at,
    }

    messages = _fallback_messages(raw_state)

    for item in messages:
        if (
            item.get("direction") == "outbound"
            and item.get("status") == "scheduled"
        ):
            item["status"] = "paused"
            item["updated_at"] = received_at

    messages.append(message)

    outreach["status"] = "replied"
    outreach["last_error"] = None
    outreach["paused_reason"] = None

    if request.thread_id:
        outreach["provider_thread_id"] = request.thread_id

    outreach["updated_at"] = received_at

    reply = {
        "id": "reply-" + uuid4().hex,
        "lead_id": request.lead_id,
        "lead_outreach_id": request.lead_outreach_id,
        "outreach_message_id": message_id,
        "provider_name": request.provider_name,
        "provider_message_id": request.provider_message_id,
        "thread_id": request.thread_id,
        "dedupe_key": dedupe_key,
        "from_email": sender_email,
        "to_email": request.to_email.strip(),
        "subject": request.subject.strip(),
        "body": request.body.strip(),
        "classification": classification.value,
        "classification_reason": classification_reason,
        "is_unsubscribe": is_unsubscribe,
        "received_at": received_at,
        "metadata": deepcopy(request.metadata),
        "created_at": _now(),
    }

    raw_state.setdefault(
        "inbound_replies",
        [],
    ).append(reply)

    if is_unsubscribe:
        suppressed = raw_state.setdefault(
            "suppression_emails",
            [],
        )
        normalized = sender_email.casefold()

        if normalized not in suppressed:
            suppressed.append(normalized)

    for event_type in (
        "reply_received",
        "reply_classified",
        "sequence_stopped_for_reply",
    ):
        outreach_delivery._fallback_event(
            raw_state,
            event_type=event_type,
            actor_id=actor_id,
            payload={
                "reply_id": reply["id"],
                "message_id": message_id,
                "classification": classification.value,
                "received_at": received_at,
            },
        )

    if is_unsubscribe:
        outreach_delivery._fallback_event(
            raw_state,
            event_type="suppression_added",
            actor_id=actor_id,
            payload={
                "reply_id": reply["id"],
                "email": sender_email,
                "reason": "Inbound unsubscribe reply",
            },
        )

    return _serialize_reply(
        reply,
        idempotent=False,
    )


def _db_existing_reply(
    settings: Settings,
    dedupe_key: str,
) -> dict[str, Any] | None:
    rows = (
        _client(settings)
        .table("inbound_reply_events")
        .select("*")
        .eq("dedupe_key", dedupe_key)
        .limit(1)
        .execute()
        .data
        or []
    )

    return rows[0] if rows else None


def _db_add_suppression(
    settings: Settings,
    *,
    email: str,
    actor_id: str,
) -> None:
    client = _client(settings)

    rows = (
        client
        .table("suppression_entries")
        .select("id")
        .eq("normalized_email", email.casefold())
        .limit(1)
        .execute()
        .data
        or []
    )

    payload = {
        "email": email,
        "suppression_kind": "unsubscribed",
        "reason": "Inbound unsubscribe reply",
        "source": "inbound_reply",
        "is_active": True,
        "created_by": actor_id,
    }

    if rows:
        client.table(
            "suppression_entries"
        ).update(
            {
                "suppression_kind": "unsubscribed",
                "reason": "Inbound unsubscribe reply",
                "source": "inbound_reply",
                "is_active": True,
            }
        ).eq(
            "id",
            rows[0]["id"],
        ).execute()
        return

    client.table(
        "suppression_entries"
    ).insert(payload).execute()


def _db_ingest(
    settings: Settings,
    actor_id: str,
    role: str,
    request: InboundReplyRequest,
) -> dict[str, Any]:
    state = outreach_delivery._context(
        settings,
        request.lead_id,
    )

    sender_email = _assert_request_matches_context(
        request,
        state,
        actor_id,
        role,
    )

    dedupe_key = _dedupe_key(request)

    existing = _db_existing_reply(
        settings,
        dedupe_key,
    )
    if existing:
        return _serialize_reply(
            existing,
            idempotent=True,
        )

    (
        classification,
        classification_reason,
        is_unsubscribe,
    ) = classify_reply(
        request.subject,
        request.body,
    )

    client = _client(settings)
    outreach = state["lead_outreach"]
    received_at = _iso(request.received_at)

    reply_rows = (
        client
        .table("inbound_reply_events")
        .insert(
            {
                "lead_id": request.lead_id,
                "lead_outreach_id": outreach["id"],
                "provider_name": request.provider_name,
                "provider_message_id": request.provider_message_id,
                "thread_id": request.thread_id,
                "dedupe_key": dedupe_key,
                "from_email": sender_email,
                "to_email": request.to_email.strip(),
                "subject": request.subject.strip(),
                "body": request.body.strip(),
                "classification": classification.value,
                "classification_reason": classification_reason,
                "is_unsubscribe": is_unsubscribe,
                "received_at": received_at,
                "metadata": request.metadata,
            }
        )
        .execute()
        .data
        or []
    )

    if not reply_rows:
        existing = _db_existing_reply(
            settings,
            dedupe_key,
        )
        if existing:
            return _serialize_reply(
                existing,
                idempotent=True,
            )

        raise RuntimeError(
            "Unable to persist inbound reply event"
        )

    reply = reply_rows[0]
    inbound_key = "reply-" + dedupe_key

    message_rows = (
        client
        .table("outreach_messages")
        .insert(
            {
                "lead_outreach_id": outreach["id"],
                "sequence_step_id": None,
                "step_number": outreach.get("current_step_number"),
                "direction": "inbound",
                "status": "replied",
                "subject": request.subject.strip(),
                "body": request.body.strip(),
                "generation_provider": request.provider_name,
                "generation_model": None,
                "provider_message_id": request.provider_message_id,
                "idempotency_key": inbound_key,
                "provider_response": {
                    "thread_id": request.thread_id,
                    "metadata": request.metadata,
                    "classification": classification.value,
                },
                "generated_at": received_at,
                "replied_at": received_at,
                "created_by": actor_id,
                "updated_by": actor_id,
            }
        )
        .execute()
        .data
        or []
    )

    if not message_rows:
        raise RuntimeError(
            "Unable to persist inbound outreach message"
        )

    message = message_rows[0]

    client.table(
        "inbound_reply_events"
    ).update(
        {
            "outreach_message_id": message["id"],
        }
    ).eq(
        "id",
        reply["id"],
    ).execute()

    client.table(
        "outreach_messages"
    ).update(
        {
            "status": "paused",
            "updated_by": actor_id,
        }
    ).eq(
        "lead_outreach_id",
        outreach["id"],
    ).eq(
        "direction",
        "outbound",
    ).eq(
        "status",
        "scheduled",
    ).execute()

    outreach_update = {
        "status": "replied",
        "last_error": None,
        "paused_reason": None,
        "updated_by": actor_id,
    }

    if request.thread_id:
        outreach_update["provider_thread_id"] = request.thread_id

    client.table(
        "lead_outreach"
    ).update(
        outreach_update
    ).eq(
        "id",
        outreach["id"],
    ).execute()

    if is_unsubscribe:
        _db_add_suppression(
            settings,
            email=sender_email,
            actor_id=actor_id,
        )

    for event_type in (
        "reply_received",
        "reply_classified",
        "sequence_stopped_for_reply",
    ):
        outreach_delivery._db_event(
            settings,
            lead_outreach_id=str(outreach["id"]),
            message_id=str(message["id"]),
            lead_id=request.lead_id,
            actor_id=actor_id,
            event_type=event_type,
            payload={
                "reply_id": reply["id"],
                "classification": classification.value,
                "received_at": received_at,
            },
        )

    if is_unsubscribe:
        outreach_delivery._db_event(
            settings,
            lead_outreach_id=str(outreach["id"]),
            message_id=str(message["id"]),
            lead_id=request.lead_id,
            actor_id=actor_id,
            event_type="suppression_added",
            payload={
                "reply_id": reply["id"],
                "email": sender_email,
                "reason": "Inbound unsubscribe reply",
            },
        )

    refreshed = (
        _db_existing_reply(
            settings,
            dedupe_key,
        )
        or reply
    )

    return _serialize_reply(
        refreshed,
        idempotent=False,
    )


def ingest_inbound_reply(
    settings: Settings,
    actor_id: str,
    role: str,
    request: InboundReplyRequest,
) -> dict[str, Any]:
    if not request.body.strip():
        raise ValueError(
            "Inbound reply body is required"
        )

    if (
        str(request.lead_id).strip() == ""
        or str(request.lead_outreach_id).strip() == ""
    ):
        raise ValueError(
            "Lead and outreach identifiers are required"
        )

    if _uses_fallback(settings):
        return _fallback_ingest(
            settings,
            actor_id,
            role,
            request,
        )

    return _db_ingest(
        settings,
        actor_id,
        role,
        request,
    )


def list_inbound_replies(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> list[dict[str, Any]]:
    state = outreach_delivery._context(
        settings,
        lead_id,
    )

    outreach_delivery._assert_access(
        state["lead"],
        actor_id,
        role,
    )

    if _uses_fallback(settings):
        return deepcopy(
            state["_raw_state"].get(
                "inbound_replies",
                [],
            )
        )

    return (
        _client(settings)
        .table("inbound_reply_events")
        .select("*")
        .eq("lead_id", lead_id)
        .order("received_at", desc=True)
        .limit(100)
        .execute()
        .data
        or []
    )
