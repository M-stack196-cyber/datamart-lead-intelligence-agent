from __future__ import annotations

import re
from typing import Any


SECRET_FIELD_NAMES = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "smtp_password",
    "app_password",
    "secret",
}
SENDER_PROVIDERS = {"gmail_oauth", "smtp", "manual_only"}
SENDER_STATUSES = {"not_connected", "connected", "disabled", "error"}
EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)


def list_sender_accounts(client: Any, *, active_only: bool = False) -> list[dict[str, Any]]:
    query = client.table("sender_accounts").select(_sender_account_select()).order("created_at", desc=True)
    if active_only:
        query = query.eq("is_active", True)
    rows = query.execute().data or []
    return [_sanitize_sender_account(row) for row in rows if isinstance(row, dict)]


def create_sender_account(
    client: Any,
    *,
    actor_id: str,
    display_name: str,
    email_address: str,
    provider: str,
    daily_send_limit: int | None = None,
) -> dict[str, Any]:
    normalized_email = _normalize_email(email_address)
    normalized_provider = _validate_provider(provider)
    _ensure_unique_email(client, normalized_email)
    payload = {
        "display_name": display_name.strip(),
        "email_address": normalized_email,
        "provider": normalized_provider,
        "status": "not_connected",
        "is_active": True,
        "daily_send_limit": daily_send_limit,
        "sent_today": 0,
        "reply_tracking_enabled": False,
        "provider_config": {},
        "created_by": actor_id,
    }
    rows = client.table("sender_accounts").insert(payload).execute().data or []
    if not rows:
        raise ValueError("Sender account could not be created")
    return _sanitize_sender_account(rows[0])


def update_sender_account(
    client: Any,
    *,
    account_id: str,
    display_name: str | None = None,
    email_address: str | None = None,
    provider: str | None = None,
    daily_send_limit: int | None = None,
    status: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    existing = get_sender_account(client, account_id)
    payload: dict[str, Any] = {}
    if display_name is not None:
        payload["display_name"] = display_name.strip()
    if email_address is not None:
        normalized_email = _normalize_email(email_address)
        if normalized_email != str(existing.get("email_address") or ""):
            _ensure_unique_email(client, normalized_email, exclude_id=account_id)
        payload["email_address"] = normalized_email
    if provider is not None:
        payload["provider"] = _validate_provider(provider)
        payload["status"] = "not_connected"
    if daily_send_limit is not None:
        payload["daily_send_limit"] = daily_send_limit
    if status is not None:
        payload["status"] = _validate_status(status)
    if is_active is not None:
        payload["is_active"] = is_active
        if not is_active:
            payload["status"] = "disabled"
    if not payload:
        return existing

    rows = client.table("sender_accounts").update(payload).eq("id", account_id).execute().data or []
    if not rows:
        raise ValueError("Sender account not found")
    return _sanitize_sender_account(rows[0])


def set_sender_account_enabled(client: Any, *, account_id: str, enabled: bool) -> dict[str, Any]:
    payload = {"is_active": enabled}
    if not enabled:
        payload["status"] = "disabled"
    rows = client.table("sender_accounts").update(payload).eq("id", account_id).execute().data or []
    if not rows:
        raise ValueError("Sender account not found")
    return _sanitize_sender_account(rows[0])


def get_sender_account(client: Any, account_id: str) -> dict[str, Any]:
    rows = (
        client.table("sender_accounts")
        .select(_sender_account_select())
        .eq("id", account_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or not isinstance(rows[0], dict):
        raise ValueError("Sender account not found")
    return _sanitize_sender_account(rows[0])


def validate_system_sender_account(client: Any, account_id: str) -> dict[str, Any]:
    account = get_sender_account(client, account_id)
    if not account.get("is_active"):
        raise ValueError("Sender account is disabled.")
    if account.get("provider") != "gmail_oauth" or account.get("status") != "connected":
        raise ValueError("Sender account is not connected for system sending.")
    daily_send_limit = account.get("daily_send_limit")
    if daily_send_limit is not None and int(account.get("sent_today") or 0) >= int(daily_send_limit):
        raise ValueError("Sender account daily send limit reached.")
    return account


def sender_for_manual_record(
    client: Any,
    *,
    sender_account_id: str | None,
    sent_from_email: str | None,
) -> tuple[str | None, str | None]:
    if sender_account_id:
        account = get_sender_account(client, sender_account_id)
        if not account.get("is_active"):
            raise ValueError("Sender account is disabled.")
        return str(account["id"]), str(account["email_address"])
    if sent_from_email:
        return None, _normalize_email(sent_from_email)
    return None, None


def contains_secret_field(payload: dict[str, Any]) -> bool:
    return any(key.casefold() in SECRET_FIELD_NAMES for key in payload)


def _ensure_unique_email(client: Any, email_address: str, *, exclude_id: str | None = None) -> None:
    rows = (
        client.table("sender_accounts")
        .select("id,email_address")
        .eq("email_address", email_address)
        .execute()
        .data
        or []
    )
    for row in rows:
        if isinstance(row, dict) and str(row.get("id") or "") != str(exclude_id or ""):
            raise ValueError("Sender account email address already exists")


def _normalize_email(email_address: str) -> str:
    value = email_address.strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError("A valid sender email address is required")
    return value


def _validate_provider(provider: str) -> str:
    value = provider.strip().casefold()
    if value not in SENDER_PROVIDERS:
        raise ValueError("Sender account provider must be gmail_oauth, smtp, or manual_only")
    return value


def _validate_status(status: str) -> str:
    value = status.strip().casefold()
    if value not in SENDER_STATUSES:
        raise ValueError("Sender account status must be not_connected, connected, disabled, or error")
    return value


def _sanitize_sender_account(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in SECRET_FIELD_NAMES and key != "provider_config"
    }


def _sender_account_select() -> str:
    return (
        "id,display_name,email_address,provider,status,is_active,daily_send_limit,"
        "sent_today,last_sent_at,reply_tracking_enabled,created_by,created_at,updated_at"
    )
