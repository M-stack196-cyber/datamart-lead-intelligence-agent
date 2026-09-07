from types import SimpleNamespace
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
import app.api.router as router_module
from app.services.vibe_discovery_cycle import approved_daily_limit


def fake_settings():
    return SimpleNamespace(
        cron_secret="test-cron-secret",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role-test",
        vibe_api_key="vibe-test-key",
        daily_vibe_lead_limit=100,
        vibe_allow_over_daily_cap=False,
    )


async def get(path: str, *, headers: dict[str, str] | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.get(path, headers=headers)


@pytest.mark.anyio
async def test_discovery_endpoint_rejects_missing_secret(
    monkeypatch,
):
    monkeypatch.setattr(
        router_module,
        "get_settings",
        fake_settings,
    )

    response = await get(
        "/internal/vibe/discovery-cycle"
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_discovery_endpoint_rejects_wrong_secret(
    monkeypatch,
):
    monkeypatch.setattr(
        router_module,
        "get_settings",
        fake_settings,
    )

    response = await get(
        "/internal/vibe/discovery-cycle",
        headers={
            "Authorization": "Bearer wrong-secret",
        },
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_discovery_endpoint_runs_mocked_cycle(
    monkeypatch,
):
    monkeypatch.setattr(
        router_module,
        "get_settings",
        fake_settings,
    )

    monkeypatch.setattr(
        router_module,
        "create_client",
        lambda *args, **kwargs: object(),
    )

    monkeypatch.setattr(
        router_module,
        "run_vibe_discovery_cycle",
        lambda *args, **kwargs: SimpleNamespace(
            requested_limit=100,
            fetched_count=100,
            stored_count=72,
            duplicate_count=28,
            qualified_count=35,
            review_count=25,
            rejected_count=40,
            evidence_count=48,
            draft_count=20,
            errors=[],
            warnings=[],
        ),
    )

    response = await get(
        "/internal/vibe/discovery-cycle",
        headers={
            "Authorization": (
                "Bearer test-cron-secret"
            ),
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "status": "completed",
        "requested_limit": 100,
        "fetched_count": 100,
        "stored_count": 72,
        "duplicate_count": 28,
        "qualified_count": 35,
        "review_count": 25,
        "rejected_count": 40,
        "evidence_count": 48,
        "draft_count": 20,
        "errors": [],
        "warnings": [],
    }


def test_daily_discovery_limit_is_safe_and_supports_staged_rollout():
    for staged_limit in (10, 25, 50, 100):
        assert approved_daily_limit(None, staged_limit) == staged_limit

    with pytest.raises(ValueError, match="requires VIBE_ALLOW_OVER_DAILY_CAP"):
        approved_daily_limit(101, 101)

    assert approved_daily_limit(125, 125, allow_over_cap=True) == 125


@pytest.mark.anyio
async def test_discovery_endpoint_rejects_limit_above_configuration(monkeypatch):
    monkeypatch.setattr(router_module, "get_settings", fake_settings)
    monkeypatch.setattr(router_module, "create_client", lambda *args, **kwargs: object())

    response = await get(
        "/internal/vibe/discovery-cycle?limit=101",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 400


def test_discovery_cycle_never_invokes_gmail_delivery():
    cycle_source = (
        Path(__file__).parents[1]
        / "app"
        / "services"
        / "vibe_discovery_cycle.py"
    ).read_text().casefold()
    persistence_source = (
        Path(__file__).parents[1]
        / "app"
        / "services"
        / "vibe_discovery_persistence.py"
    ).read_text().casefold()

    assert "gmail" not in cycle_source
    assert "send_email" not in cycle_source
    assert "gmail" not in persistence_source
    assert "send_email" not in persistence_source
