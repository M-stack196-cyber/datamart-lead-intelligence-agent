from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from email_validator import EmailNotValidError, validate_email
from supabase import create_client

from app.core.config import Settings
from app.integrations.outbound import (
    MockOutboundEmailProvider,
    OutboundEmailProvider,
    OutboundEmailRequest,
)
from app.schemas.outbound import SuppressionEntry, SuppressionKind
from app.services import outreach_generation
from app.services.outbound import (
    build_idempotency_key,
    is_suppressed,
)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _uses_fallback(settings: Settings) -> bool:
    return not (
        settings.supabase_url
        and settings.supabase_service_role_key
    )


def _client(settings: Settings):
    if _uses_fallback(settings):
        raise RuntimeError(
            "Outreach delivery persistence is not configured"
        )

    return create_client(
        settings.supabase_url or "",
        settings.supabase_service_role_key or "",
    )


def _provider(settings: Settings) -> OutboundEmailProvider:
    provider_name = (
        settings.outbound_email_provider or "mock"
    ).strip().casefold()

    if provider_name == "mock":
        return MockOutboundEmailProvider()

    raise RuntimeError(
        f"Unsupported outbound email provider: {provider_name}"
    )


def _normalize_recipient(email: str) -> str:
    try:
        return validate_email(
            email,
            check_deliverability=False,
            test_environment=email.casefold().endswith(".test"),
        ).normalized
    except EmailNotValidError as exc:
        raise ValueError(
            "A valid recipient email is required"
        ) from exc


def _assert_access(
    lead: dict[str, Any],
    actor_id: str,
    role: str,
) -> None:
    if role in {"admin", "manager"}:
        return

    if (
        role == "sales"
        and str(lead.get("assigned_to") or "") == actor_id
    ):
        return

    raise PermissionError(
        "This lead is not assigned to the current sales user"
    )


def _is_suppressed(
    settings: Settings,
    email: str,
) -> bool:
    if _uses_fallback(settings):
        suppressions = [
            SuppressionEntry(
                id="local-suppression",
                email="suppressed@datamart.test",
                suppression_kind=SuppressionKind.MANUAL,
            )
        ]

        return is_suppressed(
            email,
            suppressions,
        )

    rows = (
        _client(settings)
        .table("suppression_entries")
        .select(
            "id,email,suppression_kind,reason,source,"
            "is_active,created_by,created_at,updated_at"
        )
        .eq("normalized_email", email.casefold())
        .eq("is_active", True)
        .limit(1)
        .execute()
        .data
        or []
    )

    entries = [
        SuppressionEntry.model_validate(row)
        for row in rows
    ]

    return is_suppressed(
        email,
        entries,
    )


def _assert_lead_send_eligible(
    settings: Settings,
    lead: dict[str, Any],
    actor_id: str,
    role: str,
) -> str:
    _assert_access(
        lead,
        actor_id,
        role,
    )

    if lead.get("status") == "disqualified":
        raise ValueError(
            "Lead is disqualified and cannot receive outreach"
        )

    if not lead.get("sales_approved_at"):
        raise ValueError(
            "Lead must remain approved for sales before email sending"
        )

    recipient = _normalize_recipient(
        str(lead.get("email") or "").strip()
    )

    if _is_suppressed(
        settings,
        recipient,
    ):
        raise PermissionError(
            "Recipient is suppressed and cannot receive outreach"
        )

    return recipient


def _db_event(
    settings: Settings,
    *,
    lead_outreach_id: str,
    message_id: str,
    lead_id: str,
    actor_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    client = _client(settings)

    client.table("outreach_events").insert(
        {
            "lead_outreach_id": lead_outreach_id,
            "message_id": message_id,
            "event_type": event_type,
            "event_payload": payload,
            "created_by": actor_id,
        }
    ).execute()

    client.table("audit_log").insert(
        {
            "actor_id": actor_id,
            "action": event_type,
            "entity_type": "outreach_message",
            "entity_id": message_id,
            "details": {
                "lead_id": lead_id,
                **payload,
            },
        }
    ).execute()


def _fallback_event(
    state: dict[str, Any],
    *,
    event_type: str,
    actor_id: str,
    payload: dict[str, Any],
) -> None:
    state.setdefault("events", []).append(
        {
            "id": f"fallback-{len(state.get('events', [])) + 1}",
            "event_type": event_type,
            "event_payload": payload,
            "occurred_at": _now(),
            "created_by": actor_id,
        }
    )


def _fallback_context(
    lead_id: str,
) -> dict[str, Any]:
    lead = outreach_generation._FALLBACK_LEADS.get(lead_id)

    if not lead:
        raise ValueError("Lead not found")

    state = outreach_generation._FALLBACK_STATE.get(lead_id)

    if not state:
        raise ValueError(
            "No outreach draft exists for this lead"
        )

    if not state.get("latest_message"):
        raise ValueError(
            "No outreach message exists for this lead"
        )

    return {
        "lead": deepcopy(lead),
        "lead_outreach": state["lead_outreach"],
        "message": state["latest_message"],
        "events": state.setdefault("events", []),
        "_raw_state": state,
    }


def _db_context(
    settings: Settings,
    lead_id: str,
) -> dict[str, Any]:
    client = _client(settings)

    lead = (
        client.table("leads")
        .select("*")
        .eq("id", lead_id)
        .single()
        .execute()
        .data
    )

    if not lead:
        raise ValueError("Lead not found")

    outreach_rows = (
        client.table("lead_outreach")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not outreach_rows:
        raise ValueError(
            "No outreach record exists for this lead"
        )

    outreach = outreach_rows[0]

    message_rows = (
        client.table("outreach_messages")
        .select("*")
        .eq(
            "lead_outreach_id",
            outreach["id"],
        )
        .eq("direction", "outbound")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not message_rows:
        raise ValueError(
            "No outreach message exists for this lead"
        )

    return {
        "lead": lead,
        "lead_outreach": outreach,
        "message": message_rows[0],
    }


def _context(
    settings: Settings,
    lead_id: str,
) -> dict[str, Any]:
    if _uses_fallback(settings):
        return _fallback_context(lead_id)

    return _db_context(
        settings,
        lead_id,
    )


def approve_outreach_message(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> dict[str, Any]:
    state = _context(
        settings,
        lead_id,
    )

    lead = state["lead"]
    outreach = state["lead_outreach"]
    message = state["message"]

    _assert_access(
        lead,
        actor_id,
        role,
    )

    if role != "admin":
        raise PermissionError(
            "Admin role required for outreach approval"
        )

    if lead.get("status") == "disqualified":
        raise ValueError(
            "Lead is disqualified and cannot be approved for outreach"
        )

    if not lead.get("sales_approved_at"):
        raise ValueError(
            "Lead must be approved for sales before outreach approval"
        )

    recipient = _normalize_recipient(
        str(lead.get("email") or "").strip()
    )

    if _is_suppressed(
        settings,
        recipient,
    ):
        raise PermissionError(
            "Recipient is suppressed and cannot receive outreach"
        )

    if outreach.get("status") == "paused":
        raise ValueError(
            "Paused outreach cannot be approved"
        )

    if message.get("status") == "sent":
        raise ValueError(
            "Sent messages cannot be approved again"
        )

    if message.get("status") == "approved":
        return {
            "lead_id": lead_id,
            "message_id": message["id"],
            "status": "approved",
            "approved_at": message.get("approved_at"),
            "approved_by": message.get("approved_by"),
            "idempotent": True,
        }

    if message.get("status") != "draft":
        raise ValueError(
            "Only a draft can be approved"
        )

    approved_at = _now()

    if _uses_fallback(settings):
        message["status"] = "approved"
        message["approved_at"] = approved_at
        message["approved_by"] = actor_id

        outreach["status"] = "approved"

        raw_state = state["_raw_state"]

        _fallback_event(
            raw_state,
            event_type="outreach_approved",
            actor_id=actor_id,
            payload={
                "approved_at": approved_at,
                "approved_by": actor_id,
            },
        )

    else:
        client = _client(settings)

        rows = (
            client.table("outreach_messages")
            .update(
                {
                    "status": "approved",
                    "approved_at": approved_at,
                    "approved_by": actor_id,
                    "updated_by": actor_id,
                }
            )
            .eq("id", message["id"])
            .eq("status", "draft")
            .execute()
            .data
            or []
        )

        if not rows:
            raise ValueError(
                "Only a draft can be approved"
            )

        client.table("lead_outreach").update(
            {
                "status": "approved",
                "updated_by": actor_id,
            }
        ).eq(
            "id",
            outreach["id"],
        ).execute()

        _db_event(
            settings,
            lead_outreach_id=outreach["id"],
            message_id=message["id"],
            lead_id=lead_id,
            actor_id=actor_id,
            event_type="outreach_approved",
            payload={
                "approved_at": approved_at,
                "approved_by": actor_id,
            },
        )

    return {
        "lead_id": lead_id,
        "message_id": message["id"],
        "status": "approved",
        "approved_at": approved_at,
        "approved_by": actor_id,
        "idempotent": False,
    }


def send_outreach_message(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
) -> dict[str, Any]:
    state = _context(
        settings,
        lead_id,
    )

    lead = state["lead"]
    outreach = state["lead_outreach"]
    message = state["message"]

    recipient = _assert_lead_send_eligible(
        settings,
        lead,
        actor_id,
        role,
    )

    if outreach.get("status") == "paused":
        raise ValueError(
            "Paused outreach cannot be sent"
        )

    if message.get("status") == "draft":
        raise ValueError(
            "Draft must be approved before sending"
        )

    if message.get("status") == "sent":
        return {
            "lead_id": lead_id,
            "message_id": message["id"],
            "status": "sent",
            "provider_message_id": message.get(
                "provider_message_id"
            ),
            "sent_at": message.get("sent_at"),
            "idempotent": True,
        }

    if message.get("status") not in {
        "approved",
        "failed",
    }:
        raise ValueError(
            "Only an approved outreach message can be sent"
        )

    if not message.get("approved_at"):
        raise ValueError(
            "Outreach message has not been explicitly approved"
        )

    provider_name = (
        settings.outbound_email_provider or "mock"
    ).strip().casefold()

    idempotency_key = build_idempotency_key(
        lead_id=lead_id,
        sequence_id=str(outreach["sequence_id"]),
        step_number=int(
            message.get("step_number") or 1
        ),
        recipient_email=recipient,
        provider_name=provider_name,
    )

    subject = str(
        message.get("subject") or ""
    ).strip()

    body = str(
        message.get("body") or ""
    ).strip()

    if not subject:
        raise ValueError(
            "Approved email subject is required"
        )

    if not body:
        raise ValueError(
            "Approved email body is required"
        )

    request = OutboundEmailRequest(
        lead_id=lead_id,
        lead_outreach_id=str(outreach["id"]),
        sequence_id=str(outreach["sequence_id"]),
        step_number=int(
            message.get("step_number") or 1
        ),
        sender_email=(
            settings.gmail_sender_email
            or "outreach@datamart.test"
        ),
        recipient_email=recipient,
        subject=subject,
        body=body,
        idempotency_key=idempotency_key,
        provider_name=provider_name,
        metadata={
            "message_id": message["id"],
        },
    )

    attempted_at = _now()

    if _uses_fallback(settings):
        _fallback_event(
            state["_raw_state"],
            event_type="outreach_send_attempted",
            actor_id=actor_id,
            payload={
                "attempted_at": attempted_at,
                "provider": provider_name,
                "idempotency_key": idempotency_key,
            },
        )
    else:
        _db_event(
            settings,
            lead_outreach_id=outreach["id"],
            message_id=message["id"],
            lead_id=lead_id,
            actor_id=actor_id,
            event_type="outreach_send_attempted",
            payload={
                "attempted_at": attempted_at,
                "provider": provider_name,
                "idempotency_key": idempotency_key,
            },
        )

    provider = _provider(settings)

    try:
        result = provider.send(request)

    except Exception as exc:
        error_message = (
            str(exc)
            or "Outbound provider send failed"
        )

        if _uses_fallback(settings):
            message["status"] = "failed"
            message["error_message"] = error_message
            message["idempotency_key"] = idempotency_key

            outreach["status"] = "failed"
            outreach["last_error"] = error_message

            _fallback_event(
                state["_raw_state"],
                event_type="outreach_send_failed",
                actor_id=actor_id,
                payload={
                    "provider": provider_name,
                    "error": error_message,
                    "idempotency_key": idempotency_key,
                },
            )

        else:
            client = _client(settings)

            client.table("outreach_messages").update(
                {
                    "status": "failed",
                    "error_message": error_message,
                    "idempotency_key": idempotency_key,
                    "updated_by": actor_id,
                }
            ).eq(
                "id",
                message["id"],
            ).execute()

            client.table("lead_outreach").update(
                {
                    "status": "failed",
                    "last_error": error_message,
                    "updated_by": actor_id,
                }
            ).eq(
                "id",
                outreach["id"],
            ).execute()

            _db_event(
                settings,
                lead_outreach_id=outreach["id"],
                message_id=message["id"],
                lead_id=lead_id,
                actor_id=actor_id,
                event_type="outreach_send_failed",
                payload={
                    "provider": provider_name,
                    "error": error_message,
                    "idempotency_key": idempotency_key,
                },
            )

        raise RuntimeError(
            error_message
        ) from exc

    sent_at = (
        result.sent_at
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )

    if _uses_fallback(settings):
        message["status"] = "sent"
        message["provider_message_id"] = (
            result.provider_message_id
        )
        message["sent_at"] = sent_at
        message["error_message"] = None
        message["idempotency_key"] = idempotency_key

        outreach["status"] = "sent"
        outreach["last_error"] = None

        _fallback_event(
            state["_raw_state"],
            event_type="outreach_sent",
            actor_id=actor_id,
            payload={
                "provider": result.provider_name,
                "provider_message_id": (
                    result.provider_message_id
                ),
                "sent_at": sent_at,
                "idempotency_key": idempotency_key,
            },
        )

    else:
        client = _client(settings)

        rows = (
            client.table("outreach_messages")
            .update(
                {
                    "status": "sent",
                    "provider_message_id": (
                        result.provider_message_id
                    ),
                    "sent_at": sent_at,
                    "error_message": None,
                    "idempotency_key": idempotency_key,
                    "updated_by": actor_id,
                }
            )
            .eq("id", message["id"])
            .in_(
                "status",
                ["approved", "failed"],
            )
            .execute()
            .data
            or []
        )

        if not rows:
            refreshed = _db_context(
                settings,
                lead_id,
            )["message"]

            if refreshed.get("status") == "sent":
                return {
                    "lead_id": lead_id,
                    "message_id": refreshed["id"],
                    "status": "sent",
                    "provider_message_id": refreshed.get(
                        "provider_message_id"
                    ),
                    "sent_at": refreshed.get(
                        "sent_at"
                    ),
                    "idempotent": True,
                }

            raise RuntimeError(
                "Unable to persist outbound send result"
            )

        client.table("lead_outreach").update(
            {
                "status": "sent",
                "last_error": None,
                "updated_by": actor_id,
            }
        ).eq(
            "id",
            outreach["id"],
        ).execute()

        _db_event(
            settings,
            lead_outreach_id=outreach["id"],
            message_id=message["id"],
            lead_id=lead_id,
            actor_id=actor_id,
            event_type="outreach_sent",
            payload={
                "provider": result.provider_name,
                "provider_message_id": (
                    result.provider_message_id
                ),
                "sent_at": sent_at,
                "idempotency_key": idempotency_key,
            },
        )

    return {
        "lead_id": lead_id,
        "message_id": message["id"],
        "status": "sent",
        "provider": result.provider_name,
        "provider_message_id": (
            result.provider_message_id
        ),
        "sent_at": sent_at,
        "idempotent": False,
    }
