from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

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


def _prepare_lead() -> None:
    from app.services.outreach_generation import (
        generate_outreach_message,
    )

    generate_outreach_message(
        offline_settings(),
        "user-1",
        "admin",
        "lead-01",
    )


@pytest.fixture(autouse=True)
def reset_state() -> None:
    outreach_generation.reset_fallback_outreach_state()
    app.dependency_overrides.clear()


async def request_as(
    role: str,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    user_id: str = "user-1",
):
    from app.api import router as router_module

    settings = offline_settings()

    app.dependency_overrides[require_user] = lambda: CurrentUser(
        id=user_id,
        role=role,
        email=f"{user_id}@datamart.test",
    )

    original_get_settings = router_module.get_settings
    router_module.get_settings = lambda: settings

    try:
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.request(
                method,
                path,
                json=json,
            )
    finally:
        router_module.get_settings = original_get_settings
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_admin_can_sync_lead_to_crm() -> None:
    _prepare_lead()

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {
                "email": "lead-01@datamart.test",
            },
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["provider_key"] == "mock"
    assert payload["sync_status"] == "synced"
    assert payload["external_crm_id"]
    assert payload["idempotent"] is False


@pytest.mark.anyio
async def test_manager_can_sync_lead_to_crm() -> None:
    _prepare_lead()

    response = await request_as(
        "manager",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
        user_id="manager-1",
    )

    assert response.status_code == 200
    assert response.json()["sync_status"] == "synced"


@pytest.mark.anyio
async def test_sales_cannot_trigger_crm_sync() -> None:
    _prepare_lead()

    response = await request_as(
        "sales",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_crm_sync_is_idempotent() -> None:
    _prepare_lead()

    first = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
    )

    second = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    assert first.json()["idempotent"] is False
    assert second.json()["idempotent"] is True

    assert (
        first.json()["external_crm_id"]
        == second.json()["external_crm_id"]
    )


@pytest.mark.anyio
async def test_admin_can_get_crm_sync_state() -> None:
    _prepare_lead()

    sync = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
    )

    assert sync.status_code == 200

    response = await request_as(
        "admin",
        "GET",
        "/outreach/lead-01/crm-sync",
    )

    assert response.status_code == 200

    rows = response.json()

    assert len(rows) == 1
    assert rows[0]["provider_key"] == "mock"
    assert rows[0]["sync_status"] == "synced"


@pytest.mark.anyio
async def test_sales_can_read_assigned_lead_crm_state() -> None:
    _prepare_lead()

    sync = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
    )

    assert sync.status_code == 200

    response = await request_as(
        "sales",
        "GET",
        "/outreach/lead-01/crm-sync",
        user_id="user-1",
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.anyio
async def test_unassigned_sales_cannot_read_crm_state() -> None:
    _prepare_lead()

    response = await request_as(
        "sales",
        "GET",
        "/outreach/lead-01/crm-sync",
        user_id="sales-other",
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_provider_filter_works() -> None:
    _prepare_lead()

    sync = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
    )

    assert sync.status_code == 200

    matching = await request_as(
        "admin",
        "GET",
        "/outreach/lead-01/crm-sync?provider_key=mock",
    )

    missing = await request_as(
        "admin",
        "GET",
        "/outreach/lead-01/crm-sync?provider_key=other",
    )

    assert matching.status_code == 200
    assert len(matching.json()) == 1

    assert missing.status_code == 200
    assert missing.json() == []


@pytest.mark.anyio
async def test_empty_provider_key_is_rejected() -> None:
    _prepare_lead()

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "",
            "mapping": {},
        },
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_unsupported_provider_returns_503() -> None:
    _prepare_lead()

    response = await request_as(
        "admin",
        "POST",
        "/outreach/lead-01/crm-sync",
        json={
            "provider_key": "unsupported",
            "mapping": {},
        },
    )

    assert response.status_code == 503
    assert "Unsupported CRM provider" in response.json()["detail"]


@pytest.mark.anyio
async def test_missing_lead_returns_400() -> None:
    response = await request_as(
        "admin",
        "POST",
        "/outreach/missing-lead/crm-sync",
        json={
            "provider_key": "mock",
            "mapping": {},
        },
    )

    assert response.status_code == 400


@pytest.mark.anyio
async def test_missing_lead_state_returns_400() -> None:
    response = await request_as(
        "admin",
        "GET",
        "/outreach/missing-lead/crm-sync",
    )

    assert response.status_code == 400
