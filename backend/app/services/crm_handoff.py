from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.core.config import Settings
from app.integrations.outbound import (
    CrmHandoffRequest,
    CrmProvider,
    MockCrmProvider,
)
from app.schemas.outbound import CrmSyncStatus
from app.services import outreach_delivery
from app.services.outbound import can_manage_crm_sync


_RETRY_DELAY_MINUTES = 15


def _now_dt() -> datetime:
    return datetime.now(tz=UTC)


def _iso(value: datetime | None = None) -> str:
    current = value or _now_dt()
    return (
        current.astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _uses_fallback(settings: Settings) -> bool:
    return outreach_delivery._uses_fallback(settings)


def _client(settings: Settings):
    return outreach_delivery._client(settings)


def _provider(
    provider_key: str,
) -> CrmProvider:
    normalized = provider_key.strip().casefold()

    if normalized == "mock":
        return MockCrmProvider()

    raise RuntimeError(
        f"Unsupported CRM provider: {normalized}"
    )


def _assert_manage_access(
    lead: dict[str, Any],
    actor_id: str,
    role: str,
) -> None:
    outreach_delivery._assert_access(
        lead,
        actor_id,
        role,
    )

    if not can_manage_crm_sync(role):
        raise PermissionError(
            "Manager or admin role required for CRM sync"
        )


def _normalize_provider_key(
    provider_key: str,
) -> str:
    normalized = provider_key.strip().casefold()

    if not normalized:
        raise ValueError(
            "CRM provider key is required"
        )

    return normalized


def _idempotency_key(
    lead_id: str,
    provider_key: str,
) -> str:
    material = (
        f"crm-handoff|{lead_id}|{provider_key}"
    )

    digest = hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()

    return f"crm-{digest}"


def _serialize(
    row: dict[str, Any],
    *,
    idempotent: bool = False,
) -> dict[str, Any]:
    return {
        **deepcopy(row),
        "idempotent": idempotent,
    }


def _fallback_states(
    raw_state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return raw_state.setdefault(
        "crm_sync_states",
        {},
    )


def _fallback_event(
    raw_state: dict[str, Any],
    *,
    actor_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    outreach_delivery._fallback_event(
        raw_state,
        event_type=event_type,
        actor_id=actor_id,
        payload=payload,
    )


def _db_event(
    settings: Settings,
    *,
    lead_id: str,
    lead_outreach_id: str,
    actor_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    client = _client(settings)

    client.table("outreach_events").insert(
        {
            "lead_outreach_id": lead_outreach_id,
            "message_id": None,
            "event_type": event_type,
            "event_payload": payload,
            "created_by": actor_id,
        }
    ).execute()

    client.table("audit_log").insert(
        {
            "actor_id": actor_id,
            "action": event_type,
            "entity_type": "crm_sync_state",
            "entity_id": lead_id,
            "details": {
                "lead_id": lead_id,
                "lead_outreach_id": lead_outreach_id,
                **payload,
            },
        }
    ).execute()


def _fallback_push(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
    provider_key: str,
    mapping: dict[str, Any],
    provider: CrmProvider | None,
) -> dict[str, Any]:
    state = outreach_delivery._context(
        settings,
        lead_id,
    )

    lead = state["lead"]
    outreach = state["lead_outreach"]

    _assert_manage_access(
        lead,
        actor_id,
        role,
    )

    raw_state = state["_raw_state"]
    states = _fallback_states(raw_state)

    existing = states.get(provider_key)

    if (
        existing
        and existing.get("sync_status")
        == CrmSyncStatus.SYNCED.value
    ):
        return _serialize(
            existing,
            idempotent=True,
        )

    if existing is None:
        existing = {
            "id": f"fallback-crm-{uuid4().hex}",
            "lead_id": lead_id,
            "lead_outreach_id": outreach["id"],
            "provider_key": provider_key,
            "external_crm_id": None,
            "sync_status": CrmSyncStatus.PENDING.value,
            "mapping": deepcopy(mapping),
            "error_message": None,
            "synced_at": None,
            "next_sync_at": _iso(),
            "created_by": actor_id,
            "created_at": _iso(),
            "updated_at": _iso(),
        }

        states[provider_key] = existing
    else:
        existing["mapping"] = deepcopy(mapping)
        existing["sync_status"] = (
            CrmSyncStatus.PENDING.value
        )
        existing["error_message"] = None
        existing["updated_at"] = _iso()

    idempotency_key = _idempotency_key(
        lead_id,
        provider_key,
    )

    request = CrmHandoffRequest(
        lead_id=lead_id,
        lead_outreach_id=outreach["id"],
        provider_key=provider_key,
        external_crm_id=existing.get(
            "external_crm_id"
        ),
        mapping=deepcopy(mapping),
        idempotency_key=idempotency_key,
        metadata={
            "actor_id": actor_id,
        },
    )

    crm_provider = provider or _provider(
        provider_key
    )

    _fallback_event(
        raw_state,
        actor_id=actor_id,
        event_type="crm_sync_started",
        payload={
            "provider_key": provider_key,
            "crm_sync_state_id": existing["id"],
        },
    )

    try:
        result = crm_provider.push(request)
    except Exception as exc:
        retry_at = _now_dt() + timedelta(
            minutes=_RETRY_DELAY_MINUTES
        )

        existing["sync_status"] = (
            CrmSyncStatus.FAILED.value
        )
        existing["error_message"] = str(exc)
        existing["next_sync_at"] = _iso(
            retry_at
        )
        existing["updated_at"] = _iso()

        _fallback_event(
            raw_state,
            actor_id=actor_id,
            event_type="crm_sync_failed",
            payload={
                "provider_key": provider_key,
                "crm_sync_state_id": existing["id"],
                "error": str(exc),
                "next_sync_at": existing[
                    "next_sync_at"
                ],
            },
        )

        return _serialize(existing)

    if (
        result.sync_status
        != CrmSyncStatus.SYNCED.value
    ):
        retry_at = _now_dt() + timedelta(
            minutes=_RETRY_DELAY_MINUTES
        )

        existing["sync_status"] = (
            CrmSyncStatus.FAILED.value
        )
        existing["error_message"] = (
            "CRM provider did not return synced status"
        )
        existing["next_sync_at"] = _iso(
            retry_at
        )
        existing["updated_at"] = _iso()

        _fallback_event(
            raw_state,
            actor_id=actor_id,
            event_type="crm_sync_failed",
            payload={
                "provider_key": provider_key,
                "crm_sync_state_id": existing["id"],
                "error": existing[
                    "error_message"
                ],
            },
        )

        return _serialize(existing)

    existing["external_crm_id"] = (
        result.external_crm_id
    )
    existing["sync_status"] = (
        CrmSyncStatus.SYNCED.value
    )
    existing["error_message"] = None
    existing["synced_at"] = _iso(
        result.synced_at
    )
    existing["next_sync_at"] = _iso(
        result.synced_at or _now_dt()
    )
    existing["updated_at"] = _iso()

    _fallback_event(
        raw_state,
        actor_id=actor_id,
        event_type="crm_sync_succeeded",
        payload={
            "provider_key": provider_key,
            "crm_sync_state_id": existing["id"],
            "external_crm_id": (
                existing["external_crm_id"]
            ),
        },
    )

    return _serialize(existing)


def _db_existing(
    settings: Settings,
    lead_id: str,
    provider_key: str,
) -> dict[str, Any] | None:
    rows = (
        _client(settings)
        .table("crm_sync_state")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("provider_key", provider_key)
        .limit(1)
        .execute()
        .data
        or []
    )

    return rows[0] if rows else None


def _db_push(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
    provider_key: str,
    mapping: dict[str, Any],
    provider: CrmProvider | None,
) -> dict[str, Any]:
    state = outreach_delivery._context(
        settings,
        lead_id,
    )

    lead = state["lead"]
    outreach = state["lead_outreach"]

    _assert_manage_access(
        lead,
        actor_id,
        role,
    )

    client = _client(settings)

    existing = _db_existing(
        settings,
        lead_id,
        provider_key,
    )

    if (
        existing
        and existing.get("sync_status")
        == CrmSyncStatus.SYNCED.value
    ):
        return _serialize(
            existing,
            idempotent=True,
        )

    if existing is None:
        inserted = (
            client.table("crm_sync_state")
            .insert(
                {
                    "lead_id": lead_id,
                    "lead_outreach_id": (
                        outreach["id"]
                    ),
                    "provider_key": provider_key,
                    "sync_status": (
                        CrmSyncStatus.PENDING.value
                    ),
                    "mapping": mapping,
                    "created_by": actor_id,
                    "next_sync_at": _iso(),
                }
            )
            .execute()
            .data
            or []
        )

        if not inserted:
            existing = _db_existing(
                settings,
                lead_id,
                provider_key,
            )

            if not existing:
                raise RuntimeError(
                    "Unable to create CRM sync state"
                )
        else:
            existing = inserted[0]
    else:
        updated = (
            client.table("crm_sync_state")
            .update(
                {
                    "lead_outreach_id": (
                        outreach["id"]
                    ),
                    "sync_status": (
                        CrmSyncStatus.PENDING.value
                    ),
                    "mapping": mapping,
                    "error_message": None,
                }
            )
            .eq("id", existing["id"])
            .execute()
            .data
            or []
        )

        if updated:
            existing = updated[0]

    idempotency_key = _idempotency_key(
        lead_id,
        provider_key,
    )

    request = CrmHandoffRequest(
        lead_id=lead_id,
        lead_outreach_id=outreach["id"],
        provider_key=provider_key,
        external_crm_id=existing.get(
            "external_crm_id"
        ),
        mapping=deepcopy(mapping),
        idempotency_key=idempotency_key,
        metadata={
            "actor_id": actor_id,
        },
    )

    crm_provider = provider or _provider(
        provider_key
    )

    _db_event(
        settings,
        lead_id=lead_id,
        lead_outreach_id=outreach["id"],
        actor_id=actor_id,
        event_type="crm_sync_started",
        payload={
            "provider_key": provider_key,
            "crm_sync_state_id": existing[
                "id"
            ],
        },
    )

    try:
        result = crm_provider.push(request)
    except Exception as exc:
        retry_at = _now_dt() + timedelta(
            minutes=_RETRY_DELAY_MINUTES
        )

        failed = (
            client.table("crm_sync_state")
            .update(
                {
                    "sync_status": (
                        CrmSyncStatus.FAILED.value
                    ),
                    "error_message": str(exc),
                    "next_sync_at": _iso(
                        retry_at
                    ),
                }
            )
            .eq("id", existing["id"])
            .execute()
            .data
            or []
        )

        row = failed[0] if failed else existing

        _db_event(
            settings,
            lead_id=lead_id,
            lead_outreach_id=outreach["id"],
            actor_id=actor_id,
            event_type="crm_sync_failed",
            payload={
                "provider_key": provider_key,
                "crm_sync_state_id": (
                    existing["id"]
                ),
                "error": str(exc),
                "next_sync_at": _iso(
                    retry_at
                ),
            },
        )

        return _serialize(row)

    if (
        result.sync_status
        != CrmSyncStatus.SYNCED.value
    ):
        retry_at = _now_dt() + timedelta(
            minutes=_RETRY_DELAY_MINUTES
        )

        error_message = (
            "CRM provider did not return synced status"
        )

        failed = (
            client.table("crm_sync_state")
            .update(
                {
                    "sync_status": (
                        CrmSyncStatus.FAILED.value
                    ),
                    "error_message": (
                        error_message
                    ),
                    "next_sync_at": _iso(
                        retry_at
                    ),
                }
            )
            .eq("id", existing["id"])
            .execute()
            .data
            or []
        )

        row = failed[0] if failed else existing

        _db_event(
            settings,
            lead_id=lead_id,
            lead_outreach_id=outreach["id"],
            actor_id=actor_id,
            event_type="crm_sync_failed",
            payload={
                "provider_key": provider_key,
                "crm_sync_state_id": (
                    existing["id"]
                ),
                "error": error_message,
            },
        )

        return _serialize(row)

    synced_at = (
        result.synced_at or _now_dt()
    )

    synced = (
        client.table("crm_sync_state")
        .update(
            {
                "external_crm_id": (
                    result.external_crm_id
                ),
                "sync_status": (
                    CrmSyncStatus.SYNCED.value
                ),
                "error_message": None,
                "synced_at": _iso(
                    synced_at
                ),
                "next_sync_at": _iso(
                    synced_at
                ),
            }
        )
        .eq("id", existing["id"])
        .execute()
        .data
        or []
    )

    row = synced[0] if synced else {
        **existing,
        "external_crm_id": (
            result.external_crm_id
        ),
        "sync_status": (
            CrmSyncStatus.SYNCED.value
        ),
        "error_message": None,
        "synced_at": _iso(synced_at),
        "next_sync_at": _iso(synced_at),
    }

    _db_event(
        settings,
        lead_id=lead_id,
        lead_outreach_id=outreach["id"],
        actor_id=actor_id,
        event_type="crm_sync_succeeded",
        payload={
            "provider_key": provider_key,
            "crm_sync_state_id": existing[
                "id"
            ],
            "external_crm_id": (
                result.external_crm_id
            ),
        },
    )

    return _serialize(row)


def push_lead_to_crm(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
    provider_key: str,
    mapping: dict[str, Any] | None = None,
    *,
    provider: CrmProvider | None = None,
) -> dict[str, Any]:
    normalized_provider = (
        _normalize_provider_key(
            provider_key
        )
    )

    safe_mapping = deepcopy(
        mapping or {}
    )

    if _uses_fallback(settings):
        return _fallback_push(
            settings,
            actor_id,
            role,
            lead_id,
            normalized_provider,
            safe_mapping,
            provider,
        )

    return _db_push(
        settings,
        actor_id,
        role,
        lead_id,
        normalized_provider,
        safe_mapping,
        provider,
    )


def get_crm_sync_state(
    settings: Settings,
    actor_id: str,
    role: str,
    lead_id: str,
    provider_key: str | None = None,
) -> list[dict[str, Any]]:
    state = outreach_delivery._context(
        settings,
        lead_id,
    )

    lead = state["lead"]

    outreach_delivery._assert_access(
        lead,
        actor_id,
        role,
    )

    if _uses_fallback(settings):
        states = list(
            _fallback_states(
                state["_raw_state"]
            ).values()
        )

        if provider_key:
            normalized = (
                _normalize_provider_key(
                    provider_key
                )
            )

            states = [
                item
                for item in states
                if item.get(
                    "provider_key"
                )
                == normalized
            ]

        return [
            _serialize(item)
            for item in states
        ]

    query = (
        _client(settings)
        .table("crm_sync_state")
        .select("*")
        .eq("lead_id", lead_id)
    )

    if provider_key:
        query = query.eq(
            "provider_key",
            _normalize_provider_key(
                provider_key
            ),
        )

    rows = (
        query.order(
            "created_at",
            desc=True,
        )
        .execute()
        .data
        or []
    )

    return [
        _serialize(item)
        for item in rows
    ]
