from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.api import router as router_module
from app.api.auth import CurrentUser, require_user
from app.core.config import Settings
from app.main import app
from app.services import outreach_generation


def offline_settings(**overrides) -> Settings:
    values = {
        "supabase_url": None,
        "supabase_service_role_key": None,
        "aws_bearer_token_bedrock": None,
        "bedrock_model_id": None,
        **overrides,
    }

    return Settings(
        _env_file=None,
        **values,
    )


@pytest.fixture(autouse=True)
def reset_state():
    outreach_generation._FALLBACK_STATE.clear()
    outreach_generation._FALLBACK_LEADS.clear()
    app.dependency_overrides.clear()

    yield

    outreach_generation._FALLBACK_STATE.clear()
    outreach_generation._FALLBACK_LEADS.clear()
    app.dependency_overrides.clear()


def seed_lead(
    *,
    lead_id: str = "phase-g-api-lead",
    assigned_to: str | None = "sales-1",
):
    now = datetime.now(tz=UTC)

    outreach_generation._FALLBACK_LEADS[lead_id] = {
        "id": lead_id,
        "name": "Phase G API Lead",
        "email": "phase-g-api@example.com",
        "status": "qualified",
        "assigned_to": assigned_to,
    }

    outreach_generation._FALLBACK_STATE[lead_id] = {
        "lead_outreach": {
            "id": "outreach-phase-g-api",
            "lead_id": lead_id,
        },
        "latest_message": {
            "id": "message-phase-g-api",
            "lead_outreach_id": "outreach-phase-g-api",
            "direction": "outbound",
            "status": "sent",
            "subject": "Phase G",
            "body": "Phase G message",
            "sent_at": (
                now - timedelta(minutes=20)
            ).isoformat(),
        },
        "messages": [],
        "events": [
            {
                "id": "event-sent",
                "event_type": "outreach_sent",
                "event_payload": {},
                "occurred_at": (
                    now - timedelta(minutes=20)
                ).isoformat(),
            }
        ],
        "inbound_reply_events": [
            {
                "id": "reply-api-1",
                "lead_id": lead_id,
                "lead_outreach_id": "outreach-phase-g-api",
                "classification": "meeting_request",
                "is_unsubscribe": False,
                "from_email": "phase-g-api@example.com",
                "subject": "Meeting",
                "received_at": (
                    now - timedelta(minutes=10)
                ).isoformat(),
            }
        ],
        "crm_sync_states": {
            "mock": {
                "id": "crm-api-1",
                "lead_id": lead_id,
                "lead_outreach_id": "outreach-phase-g-api",
                "provider_key": "mock",
                "external_crm_id": "mock-crm-api",
                "sync_status": "synced",
                "error_message": None,
                "synced_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "created_at": now.isoformat(),
            }
        },
    }

    return lead_id


async def request_as(
    role: str,
    method: str,
    path: str,
    *,
    user_id: str | None = None,
):
    resolved_user_id = user_id or f"{role}-1"

    async def override_user():
        return CurrentUser(
            id=resolved_user_id,
            email=f"{resolved_user_id}@example.com",
            role=role,
        )

    app.dependency_overrides[
        require_user
    ] = override_user

    transport = httpx.ASGITransport(
        app=app
    )

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.request(
            method,
            path,
        )


@pytest.fixture
def patch_settings(monkeypatch):
    settings = offline_settings()

    monkeypatch.setattr(
        router_module,
        "get_settings",
        lambda: settings,
    )

    return settings


@pytest.mark.anyio
async def test_admin_can_get_timeline(
    patch_settings,
):
    lead_id = seed_lead()

    response = await request_as(
        "admin",
        "GET",
        f"/outreach/{lead_id}/timeline",
    )

    assert response.status_code == 200

    payload = response.json()

    assert len(payload) == 3
    assert any(
        item["source"] == "inbound_reply"
        for item in payload
    )


@pytest.mark.anyio
async def test_admin_can_get_analytics(
    patch_settings,
):
    lead_id = seed_lead()

    response = await request_as(
        "admin",
        "GET",
        f"/outreach/{lead_id}/analytics",
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["lead_id"] == lead_id
    assert payload["timeline_count"] == 3

    metrics = payload["metrics"]

    assert metrics["sent_count"] == 1
    assert metrics["reply_count"] == 1
    assert metrics["reply_rate"] == 1.0
    assert (
        metrics["meeting_request_count"]
        == 1
    )
    assert metrics["crm_synced_count"] == 1


@pytest.mark.anyio
async def test_manager_can_get_analytics(
    patch_settings,
):
    lead_id = seed_lead(
        assigned_to="sales-other",
    )

    response = await request_as(
        "manager",
        "GET",
        f"/outreach/{lead_id}/analytics",
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_assigned_sales_can_get_timeline(
    patch_settings,
):
    lead_id = seed_lead(
        assigned_to="sales-1",
    )

    response = await request_as(
        "sales",
        "GET",
        f"/outreach/{lead_id}/timeline",
        user_id="sales-1",
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_assigned_sales_can_get_analytics(
    patch_settings,
):
    lead_id = seed_lead(
        assigned_to="sales-1",
    )

    response = await request_as(
        "sales",
        "GET",
        f"/outreach/{lead_id}/analytics",
        user_id="sales-1",
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_unassigned_sales_timeline_forbidden(
    patch_settings,
):
    lead_id = seed_lead(
        assigned_to="sales-2",
    )

    response = await request_as(
        "sales",
        "GET",
        f"/outreach/{lead_id}/timeline",
        user_id="sales-1",
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_unassigned_sales_analytics_forbidden(
    patch_settings,
):
    lead_id = seed_lead(
        assigned_to="sales-2",
    )

    response = await request_as(
        "sales",
        "GET",
        f"/outreach/{lead_id}/analytics",
        user_id="sales-1",
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_missing_lead_timeline_returns_400(
    patch_settings,
):
    response = await request_as(
        "admin",
        "GET",
        "/outreach/missing-lead/timeline",
    )

    assert response.status_code == 400


@pytest.mark.anyio
async def test_missing_lead_analytics_returns_400(
    patch_settings,
):
    response = await request_as(
        "admin",
        "GET",
        "/outreach/missing-lead/analytics",
    )

    assert response.status_code == 400
