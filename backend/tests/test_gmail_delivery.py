import base64
from unittest.mock import Mock, patch

import pytest

from app.api.router import _send_approved_email
from app.core.config import Settings
from app.integrations.gmail import GmailClient, GmailDelivery, GmailDeliveryError
from app.services.email_delivery import EmailDeliveryService
from app.services.gmail_oauth import encrypt_token


class FakeTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent = []

    def send(self, **message):
        self.sent.append(message)
        if self.fail:
            raise GmailDeliveryError("Gmail provider request failed")
        return GmailDelivery(message_id="gmail-message-1")


class FakeRpcClient:
    def __init__(self) -> None:
        self.calls = []
        self.current = ""
        self.rows = {
            "sender_accounts": [
                {
                    "id": "sender-1",
                    "display_name": "Datamart Sales",
                    "email_address": "sales@datamart.com",
                    "provider": "gmail_oauth",
                    "status": "connected",
                    "is_active": True,
                    "daily_send_limit": 50,
                    "sent_today": 0,
                    "last_sent_at": None,
                    "reply_tracking_enabled": False,
                    "created_by": "admin-1",
                    "created_at": "2026-09-15T00:00:00Z",
                    "updated_at": "2026-09-15T00:00:00Z",
                }
            ],
            "sender_account_oauth_tokens": [
                {
                    "id": "token-1",
                    "sender_account_id": "sender-1",
                    "provider": "gmail",
                    "encrypted_refresh_token": encrypt_token(configured_settings(), "refresh-token"),
                }
            ],
            "outreach_drafts": [{"id": "draft-1", "sent_at": None}],
            "email_delivery_attempts": [],
        }

    def table(self, name):
        self.table_name = name
        self.operation = "select"
        self.payload = None
        self.filters = []
        return self

    def select(self, value):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def order(self, *args, **kwargs):
        return self

    def rpc(self, name, payload):
        self.current = name
        self.calls.append((name, payload))
        if hasattr(self, "operation"):
            del self.operation
        return self

    def execute(self):
        if hasattr(self, "operation"):
            rows = self.rows.get(self.table_name, [])
            filtered = rows
            for key, value in self.filters:
                filtered = [row for row in filtered if row.get(key) == value]
            if self.operation == "update":
                for row in filtered:
                    row.update(self.payload)
                return type("Response", (), {"data": filtered})()
            del self.operation
            return type("Response", (), {"data": filtered[: getattr(self, "limit_value", len(filtered))]})()
        if self.current == "begin_email_delivery_attempt":
            data = {
                "attempt_id": "attempt-1",
                "sender": "sales@datamart.com",
                "recipient": "lead@example.com",
                "subject": "Approved subject",
                "body": "Approved body",
            }
        else:
            data = {"id": "attempt-1", "status": "sent"}
        return type("Response", (), {"data": data})()


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
    )


def test_email_delivery_service_uses_fake_transport_and_validates_addresses() -> None:
    transport = FakeTransport()
    delivery = EmailDeliveryService(transport).send(
        sender="sales@datamart.com",
        recipient="lead@example.com",
        subject="Approved subject",
        body="Approved body",
    )

    assert delivery.message_id == "gmail-message-1"
    assert transport.sent[0]["recipient"] == "lead@example.com"
    with pytest.raises(ValueError, match="valid sender and recipient"):
        EmailDeliveryService(transport).send(
            sender="bad", recipient="also-bad", subject="Subject", body="Body"
        )


def test_gmail_adapter_sends_rfc_message_without_exposing_credentials() -> None:
    token_response = Mock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {"access_token": "access-token"}
    send_response = Mock()
    send_response.raise_for_status.return_value = None
    send_response.json.return_value = {"id": "gmail-message-1"}

    with patch(
        "app.integrations.gmail.client.httpx.post",
        side_effect=[token_response, send_response],
    ) as post:
        result = GmailClient("client-id", "client-secret", "refresh-token").send(
            sender="sales@datamart.test",
            recipient="lead@example.com",
            subject="Approved subject",
            body="Approved body",
        )

    raw = post.call_args_list[1].kwargs["json"]["raw"]
    decoded = base64.urlsafe_b64decode(raw).decode()
    assert result.message_id == "gmail-message-1"
    assert "Approved subject" in decoded
    assert "Approved body" in decoded
    assert "client-secret" not in str(post.call_args_list[1])
    assert "refresh-token" not in str(post.call_args_list[1])


def test_send_records_success_and_failure_with_fake_transports() -> None:
    successful_client = FakeRpcClient()
    with patch("app.api.router._backend_client", return_value=successful_client), patch(
        "app.api.router.GmailClient", return_value=FakeTransport()
    ):
        result = _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-1",
            type("Request", (), {"sender_account_id": "sender-1", "reply_wait_days": 4, "next_followup_decision_at": None})(),
        )

    assert result["status"] == "sent"
    assert successful_client.calls[-1][1]["succeeded"] is True
    assert successful_client.calls[-1][1]["provider_message_id"] == "gmail-message-1"

    failed_client = FakeRpcClient()
    with patch("app.api.router._backend_client", return_value=failed_client), patch(
        "app.api.router.GmailClient", return_value=FakeTransport(fail=True)
    ), pytest.raises(GmailDeliveryError, match="Gmail provider request failed"):
        _send_approved_email(
            configured_settings(),
            "actor-1",
            "draft-1",
            type("Request", (), {"sender_account_id": "sender-1", "reply_wait_days": 4, "next_followup_decision_at": None})(),
        )

    assert failed_client.calls[-1][1]["succeeded"] is False
    assert failed_client.calls[-1][1]["safe_error"] == "Gmail provider request failed"
