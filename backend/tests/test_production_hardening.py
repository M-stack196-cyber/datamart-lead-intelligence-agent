import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app


def test_production_mode_requires_core_configuration() -> None:
    with pytest.raises(ValueError, match="Production requires"):
        Settings(
            app_env="production",
            supabase_url=None,
            supabase_anon_key=None,
            supabase_service_role_key=None,
            database_url=None,
        )


@pytest.mark.anyio
async def test_health_reports_readiness_state() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert "ready" in payload
    assert isinstance(payload["ready"], bool)
