from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.core.config import Settings
from app.main import app
from app.services import outreach_generation
from app.services.outreach_delivery import (
    approve_outreach_message,
    send_outreach_message,
)
from app.services.outreach_generation import (
    generate_outreach_message,
    reset_fallback_outreach_state,
)
from app.services.sequence_execution import schedule_next_followup


def offline_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="development",
        outbound_email_provider="mock",
        supabase_url=None,
        supabase_service_role_key=None,
        gmail_sender_email="outreach@datamart.test",
        aws_bearer_token_bedrock=None,
        bedrock_model_id=None,
    )


@pytest.fixture(autouse=True)
def reset_state() -> None:
    reset_fallback_outreach_state()


def start_sequence(
    settings: Settings,
    *,
    lead_id: str = "lead-01",
) -> dict:
    generated = generate_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
        channel="email",
    )

    approve_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
    )

    send_outreach_message(
        settings,
        "user-1",
        "admin",
        lead_id,
    )

    schedule_next_followup(
        settings,
        "user-1",
        "admin",
        lead_id,
    )

    return generated


async def request_as(
    role: str,
    method: str,
    path: str,
    payload: dict | None = None,
    *,
    user_id: str = "user-1",
    settings: Settings | None = None,
):
    async def override_user() -> CurrentUser:
        return CurrentUser(
            id=user_id,
            email="sales@datamart.test",
            role=role,
        )

    app.dependency_overrides[require_user] = override_user

    try:
        with patch(
            "app.api.router.get_settings",
            return_value=settings or offline_settings(),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.request(
                    method,
                    path,
                    json=payload,
                )
    finally:
        app.dependency_overrides.clear()


def reply_payload(
    lead_outreach_id: str,
    *,
    body: str = "I'm interested. Happy to discuss.",
    from_email: str = "lead-01@datamart.test",
    provider_message_id: str = "api-reply-001",
) -> dict:
    return {
        "provider_name": "mock",
        "lead_outreach_id": lead_outreach_id,
        "thread_id": "thread-api-001",
        "provider_message_id": provider_message_id,
        "from_email": from_email,
        "to_email": "outreach@datamart.test",
        "subject": "Re: quick question",
        "body": body,
        "received_at": datetime.now(tz=UTC).isoformat(),
        "metadata": {
            "source": "api-test",
        },
    }


@pytest.mark.anyio
async def test_admin_can_ingest_reply() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"]
        ),
        settings=settings,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["classification"] == "interested"
    assert data["idempotent"] is False
    assert data["lead_id"] == "lead-01"
    assert data["lead_outreach_id"] == generated["lead_outreach_id"]


@pytest.mark.anyio
async def test_get_replies_returns_ingested_reply() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"]
        ),
        settings=settings,
    )

    response = await request_as(
        "admin",
        "GET",
        "/outreach/lead-01/replies",
        settings=settings,
    )

    assert response.status_code == 200

    replies = response.json()

    assert len(replies) == 1
    assert replies[0]["classification"] == "interested"
    assert replies[0]["from_email"] == "lead-01@datamart.test"


@pytest.mark.anyio
async def test_duplicate_reply_is_idempotent() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    payload = reply_payload(
        generated["lead_outreach_id"],
        provider_message_id="duplicate-api-reply",
    )

    first = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        payload,
        settings=settings,
    )

    second = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        payload,
        settings=settings,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["idempotent"] is False
    assert second.json()["idempotent"] is True
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.anyio
async def test_assigned_sales_user_can_ingest_reply() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    response = await request_as(
        "sales",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"],
            body="What is the implementation timeline?",
            provider_message_id="sales-api-reply",
        ),
        user_id="user-1",
        settings=settings,
    )

    assert response.status_code == 200
    assert response.json()["classification"] == "question"


@pytest.mark.anyio
async def test_unassigned_sales_user_cannot_ingest_reply() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    response = await request_as(
        "sales",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"],
            provider_message_id="blocked-sales-api-reply",
        ),
        user_id="different-sales-user",
        settings=settings,
    )

    assert response.status_code == 403
    assert "not assigned" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_wrong_lead_outreach_id_is_rejected() -> None:
    settings = offline_settings()
    start_sequence(settings)

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            "wrong-outreach-id",
            provider_message_id="wrong-outreach-api-reply",
        ),
        settings=settings,
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_wrong_sender_email_is_rejected() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"],
            from_email="someone-else@datamart.test",
            provider_message_id="wrong-sender-api-reply",
        ),
        settings=settings,
    )

    assert response.status_code == 400
    assert "sender does not match" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_empty_reply_body_is_validation_error() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    payload = reply_payload(
        generated["lead_outreach_id"],
        provider_message_id="empty-body-api-reply",
    )
    payload["body"] = ""

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        payload,
        settings=settings,
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_reply_marks_sequence_replied() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    reply = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"],
            provider_message_id="sequence-api-reply",
        ),
        settings=settings,
    )

    sequence = await request_as(
        "admin",
        "GET",
        "/outreach/lead-01/sequence",
        settings=settings,
    )

    assert reply.status_code == 200
    assert sequence.status_code == 200
    assert sequence.json()["status"] == "replied"


@pytest.mark.anyio
async def test_unsubscribe_reply_is_classified() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"],
            body="Please unsubscribe me from future emails.",
            provider_message_id="unsubscribe-api-reply",
        ),
        settings=settings,
    )

    assert response.status_code == 200
    assert response.json()["classification"] == "unsubscribe"
    assert response.json()["is_unsubscribe"] is True


@pytest.mark.anyio
async def test_analyst_role_cannot_access_reply_endpoint() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    response = await request_as(
        "analyst",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"],
            provider_message_id="analyst-api-reply",
        ),
        settings=settings,
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_unassigned_sales_user_cannot_list_replies() -> None:
    settings = offline_settings()
    generated = start_sequence(settings)

    await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/replies",
        reply_payload(
            generated["lead_outreach_id"],
            provider_message_id="list-access-api-reply",
        ),
        settings=settings,
    )

    response = await request_as(
        "sales",
        "GET",
        "/outreach/lead-01/replies",
        user_id="different-sales-user",
        settings=settings,
    )

    assert response.status_code == 403
