from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.api.router import _send_approved_email
from app.core.config import Settings
from app.integrations.gmail import GmailDelivery
from app.main import app
from app.services.gmail_oauth import encrypt_token, sign_oauth_state
from app.services.next_followup_drafts import mark_draft_manually_sent
from app.services.sender_accounts import create_sender_account


ROOT = Path(__file__).resolve().parents[2]


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, value):
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def order(self, *args, **kwargs):
        return self

    def execute(self):
        rows = self.client.rows.setdefault(self.table_name, [])
        if self.operation == "insert":
            payload = {"id": f"{self.table_name}-{len(rows) + 1}", **self.payload}
            rows.append(payload)
            self.client.inserts.setdefault(self.table_name, []).append(payload)
            return SimpleNamespace(data=[payload])

        filtered = rows
        for key, value in self.filters:
            filtered = [row for row in filtered if row.get(key) == value]

        if self.operation == "update":
            for row in filtered:
                row.update(self.payload)
            self.client.updates.setdefault(self.table_name, []).append(self.payload)
            return SimpleNamespace(data=filtered)

        if self.operation == "delete":
            for row in list(filtered):
                rows.remove(row)
            return SimpleNamespace(data=filtered)

        return SimpleNamespace(data=filtered[: getattr(self, "limit_value", len(filtered))])


class FakeClient:
    def __init__(self):
        self.inserts = {}
        self.updates = {}
        self.rpc_calls = []
        self.current_rpc = ""
        self.rows = {
            "sender_accounts": [],
            "sender_account_oauth_tokens": [],
            "outreach_drafts": [
                {
                    "id": "draft-email-1",
                    "lead_id": "lead-1",
                    "channel": "email",
                    "subject": "Subject",
                    "body": "Body",
                    "status": "approved",
                    "sequence_step": 1,
                    "evidence_ids": [],
                    "review_notes": None,
                    "sent_at": None,
                    "manual_sent_at": None,
                    "reply_wait_days": None,
                    "next_followup_decision_at": None,
                    "followup_stopped_at": None,
                    "followup_stop_reason": None,
                    "sender_account_id": None,
                    "sent_from_email": None,
                }
            ],
            "email_delivery_attempts": [],
            "audit_log": [],
        }

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, payload):
        self.current_rpc = name
        self.rpc_calls.append((name, payload))
        return self

    def execute(self):
        if self.current_rpc == "begin_email_delivery_attempt":
            data = {
                "attempt_id": "attempt-1",
                "sender": self.rpc_calls[-1][1]["sender_email"],
                "recipient": "lead@example.com",
                "subject": "Approved subject",
                "body": "Approved body",
            }
        else:
            data = {"id": "attempt-1", "status": "sent"}
        return SimpleNamespace(data=data)


class FakeTransport:
    def send(self, **message):
        return GmailDelivery(message_id="gmail-message-1")


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-key",
        gmail_client_id="client-id",
        gmail_client_secret="client-secret",
        gmail_refresh_token="refresh-token",
        gmail_sender_email="sales@datamart.com",
        gmail_token_encryption_key="unit-test-token-key",
        gmail_oauth_redirect_uri="http://test/gmail/oauth/callback",
        frontend_url="http://frontend.test",
    )


async def request_as(role: str, method: str, path: str, json: dict | None = None):
    async def override_user() -> CurrentUser:
        return CurrentUser(id="user-1", email="user@datamart.test", role=role)

    app.dependency_overrides[require_user] = override_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()


def add_sender(client, *, status="connected", provider="gmail_oauth", is_active=True):
    row = {
        "id": "sender-1",
        "display_name": "Datamart Sales",
        "email_address": "sales@datamart.com",
        "provider": provider,
        "status": status,
        "is_active": is_active,
        "daily_send_limit": 50,
        "sent_today": 0,
        "last_sent_at": None,
        "reply_tracking_enabled": False,
        "provider_config": {"access_token": "never-return"},
        "created_by": "admin-1",
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
    }
    client.rows["sender_accounts"].append(row)
    return row


def add_token(client, sender_account_id="sender-1"):
    row = {
        "id": "token-1",
        "sender_account_id": sender_account_id,
        "provider": "gmail",
        "encrypted_access_token": encrypt_token(configured_settings(), "access-token"),
        "encrypted_refresh_token": encrypt_token(configured_settings(), "refresh-token"),
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/gmail.send",
        "expires_at": "2026-09-15T01:00:00Z",
        "google_email": "sales@datamart.com",
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
    }
    client.rows["sender_account_oauth_tokens"].append(row)
    return row


def test_admin_can_create_sender_account_without_secrets():
    client = FakeClient()

    result = create_sender_account(
        client,
        actor_id="admin-1",
        display_name="Datamart Sales",
        email_address="Sales@DataMart.com",
        provider="gmail_oauth",
        daily_send_limit=50,
    )

    assert result["email_address"] == "sales@datamart.com"
    assert result["status"] == "not_connected"
    assert "provider_config" not in result
    assert "access_token" not in result
    assert client.inserts["sender_accounts"][0]["provider_config"] == {}


def test_sender_accounts_migration_guards_optional_email_delivery_attempts_table():
    migration = (ROOT / "supabase" / "migrations" / "20260915143000_add_sender_accounts.sql").read_text()

    assert "alter table public.outreach_drafts" in migration
    assert "add column if not exists sender_account_id uuid references public.sender_accounts(id)" in migration
    assert "if to_regclass('public.email_delivery_attempts') is not null then" in migration
    guarded_block = migration.split("if to_regclass('public.email_delivery_attempts') is not null then", 1)[1]
    assert "alter table public.email_delivery_attempts" in guarded_block
    assert "create index if not exists email_delivery_attempts_sender_account_idx" in guarded_block


def test_oauth_token_migration_keeps_tokens_service_role_only():
    migration = (ROOT / "supabase" / "migrations" / "20260915150000_add_sender_account_oauth_tokens.sql").read_text()

    assert "create table if not exists public.sender_account_oauth_tokens" in migration
    assert "encrypted_access_token text" in migration
    assert "encrypted_refresh_token text" in migration
    assert "alter table public.sender_account_oauth_tokens enable row level security" in migration
    assert "revoke all on table public.sender_account_oauth_tokens from anon, authenticated" in migration
    assert "provider_config" not in migration


def test_sender_account_email_uniqueness():
    client = FakeClient()
    add_sender(client)

    with pytest.raises(ValueError, match="already exists"):
        create_sender_account(
            client,
            actor_id="admin-1",
            display_name="Other",
            email_address="sales@datamart.com",
            provider="manual_only",
        )


@pytest.mark.anyio
async def test_gmail_connect_url_rejects_sales_user():
    response = await request_as("sales", "POST", "/sender-accounts/sender-1/gmail/connect")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_gmail_connect_url_requires_gmail_oauth_provider():
    fake = FakeClient()
    add_sender(fake, provider="manual_only", status="not_connected")
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router.get_settings", return_value=configured_settings()),
    ):
        response = await request_as("manager", "POST", "/sender-accounts/sender-1/gmail/connect")

    assert response.status_code == 400
    assert "gmail_oauth" in response.json()["detail"]


@pytest.mark.anyio
async def test_gmail_connect_url_returns_authorization_url_without_tokens():
    fake = FakeClient()
    add_sender(fake, provider="gmail_oauth", status="not_connected")
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router.get_settings", return_value=configured_settings()),
    ):
        response = await request_as("admin", "POST", "/sender-accounts/sender-1/gmail/connect")

    assert response.status_code == 200
    body = response.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "gmail.send" in body["authorization_url"]
    assert "access_token" not in body
    assert "refresh_token" not in body


@pytest.mark.anyio
async def test_gmail_oauth_callback_stores_encrypted_tokens_and_marks_connected():
    fake = FakeClient()
    add_sender(fake, provider="gmail_oauth", status="not_connected")
    settings = configured_settings()
    state = sign_oauth_state(settings, sender_account_id="sender-1")
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router.get_settings", return_value=settings),
        patch(
            "app.api.router.exchange_gmail_code",
            return_value={
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_type": "Bearer",
                "scope": "https://www.googleapis.com/auth/gmail.send",
                "expires_in": 3600,
            },
        ),
        patch("app.api.router.fetch_google_email", return_value="sales@datamart.com"),
    ):
        response = await request_as(
            "sales",
            "GET",
            f"/gmail/oauth/callback?code=code-1&state={state}",
        )

    assert response.status_code in {302, 307}
    token = fake.rows["sender_account_oauth_tokens"][0]
    assert token["encrypted_refresh_token"] != "refresh-token"
    assert token["encrypted_access_token"] != "access-token"
    assert "provider_config" not in token
    assert fake.rows["sender_accounts"][0]["status"] == "connected"


@pytest.mark.anyio
async def test_gmail_disconnect_removes_tokens_and_marks_not_connected():
    fake = FakeClient()
    add_sender(fake)
    add_token(fake)
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router.get_settings", return_value=configured_settings()),
    ):
        response = await request_as("admin", "PATCH", "/sender-accounts/sender-1/gmail/disconnect")

    assert response.status_code == 200
    assert fake.rows["sender_account_oauth_tokens"] == []
    assert fake.rows["sender_accounts"][0]["status"] == "not_connected"


@pytest.mark.anyio
async def test_sender_account_api_rejects_secret_fields_and_sanitizes_response():
    fake = FakeClient()
    with patch("app.api.router._backend_client", return_value=fake):
        rejected = await request_as(
            "admin",
            "POST",
            "/sender-accounts",
            {
                "display_name": "Datamart Sales",
                "email_address": "sales@datamart.com",
                "provider": "gmail_oauth",
                "password": "do-not-store",
            },
        )
        created = await request_as(
            "admin",
            "POST",
            "/sender-accounts",
            {
                "display_name": "Datamart Sales",
                "email_address": "sales@datamart.com",
                "provider": "gmail_oauth",
                "daily_send_limit": 50,
            },
        )

    assert rejected.status_code == 400
    assert created.status_code == 200
    body = created.json()
    assert body["message"] is None
    assert "provider_config" not in body["sender_account"]


def test_not_connected_sender_cannot_be_used_for_system_send():
    client = FakeClient()
    add_sender(client, status="not_connected")

    with patch("app.api.router._backend_client", return_value=client), pytest.raises(
        ValueError, match="not connected"
    ):
        _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-email-1",
            SimpleNamespace(confirm=True, sender_account_id="sender-1", reply_wait_days=4, next_followup_decision_at=None),
        )

    assert client.rpc_calls == []


def test_disabled_sender_cannot_be_used_for_system_send():
    client = FakeClient()
    add_sender(client, is_active=False)

    with patch("app.api.router._backend_client", return_value=client), pytest.raises(
        ValueError, match="disabled"
    ):
        _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-email-1",
            SimpleNamespace(confirm=True, sender_account_id="sender-1", reply_wait_days=4, next_followup_decision_at=None),
        )

    assert client.rpc_calls == []


def test_sender_at_daily_limit_cannot_be_used_for_system_send():
    client = FakeClient()
    sender = add_sender(client)
    sender["sent_today"] = 50
    sender["daily_send_limit"] = 50

    with patch("app.api.router._backend_client", return_value=client), pytest.raises(
        ValueError, match="daily send limit"
    ):
        _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-email-1",
            SimpleNamespace(confirm=True, sender_account_id="sender-1", reply_wait_days=4, next_followup_decision_at=None),
        )

    assert client.rpc_calls == []


def test_system_send_requires_sender_account_id():
    client = FakeClient()

    with patch("app.api.router._backend_client", return_value=client), pytest.raises(
        ValueError, match="sender_account_id is required"
    ):
        _send_approved_email(configured_settings(), "actor-1", "draft-email-1", None)

    assert client.rpc_calls == []


def test_system_send_requires_reply_wait_timing():
    client = FakeClient()
    add_sender(client)
    add_token(client)

    with patch("app.api.router._backend_client", return_value=client), pytest.raises(
        ValueError, match="Reply wait period is required"
    ):
        _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-email-1",
            SimpleNamespace(confirm=True, sender_account_id="sender-1", reply_wait_days=None, next_followup_decision_at=None),
        )

    assert client.rpc_calls == []


def test_system_send_rejects_both_reply_wait_and_custom_decision_time():
    client = FakeClient()
    add_sender(client)
    add_token(client)

    with patch("app.api.router._backend_client", return_value=client), pytest.raises(
        ValueError, match="Choose reply_wait_days"
    ):
        _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-email-1",
            SimpleNamespace(
                confirm=True,
                sender_account_id="sender-1",
                reply_wait_days=4,
                next_followup_decision_at="2026-09-20T00:00:00Z",
            ),
        )

    assert client.rpc_calls == []


def test_system_send_stores_selected_sender_on_draft_and_attempt():
    client = FakeClient()
    add_sender(client)
    add_token(client)

    with patch("app.api.router._backend_client", return_value=client), patch(
        "app.api.router.GmailClient", return_value=FakeTransport()
    ):
        result = _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-email-1",
            SimpleNamespace(confirm=True, sender_account_id="sender-1", reply_wait_days=4, next_followup_decision_at=None),
        )

    assert result["sender_account_id"] == "sender-1"
    assert result["sent_from_email"] == "sales@datamart.com"
    assert client.rows["outreach_drafts"][0]["sender_account_id"] == "sender-1"
    assert client.rows["outreach_drafts"][0]["sent_from_email"] == "sales@datamart.com"
    assert client.rows["sender_accounts"][0]["sent_today"] == 1
    assert client.rows["sender_accounts"][0]["last_sent_at"]
    assert client.rpc_calls[0][1]["sender_email"] == "sales@datamart.com"


def test_manual_sent_records_sender_account_and_still_requires_reply_wait():
    client = FakeClient()
    add_sender(client, provider="manual_only", status="not_connected")

    with pytest.raises(ValueError, match="Reply wait period is required"):
        mark_draft_manually_sent(client, draft_id="draft-email-1", actor_id="user-1", sender_account_id="sender-1")

    result = mark_draft_manually_sent(
        client,
        draft_id="draft-email-1",
        actor_id="user-1",
        reply_wait_days=4,
        sender_account_id="sender-1",
    )

    assert result["status"] == "manual_sent"
    assert result["sender_account_id"] == "sender-1"
    assert result["sent_from_email"] == "sales@datamart.com"


def test_manual_sent_can_record_freeform_sent_from_email():
    client = FakeClient()

    result = mark_draft_manually_sent(
        client,
        draft_id="draft-email-1",
        actor_id="user-1",
        reply_wait_days=4,
        sent_from_email=" Rep@DataMart.com ",
    )

    assert result["sender_account_id"] is None
    assert result["sent_from_email"] == "rep@datamart.com"
