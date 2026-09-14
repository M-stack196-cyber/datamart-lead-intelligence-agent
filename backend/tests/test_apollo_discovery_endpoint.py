from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
import app.api.router as router_module
from app.lead_sources import NormalizedLead
from app.lead_sources.base import ProviderAuthError


def fake_settings(api_key: str | None = "apollo-test-key"):
    return SimpleNamespace(
        cron_secret="test-cron-secret",
        apollo_api_key=api_key,
        apollo_base_url="https://apollo.test",
    )


async def get(path: str, *, headers: dict[str, str] | None = None):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.get(path, headers=headers)


@pytest.mark.anyio
async def test_apollo_discovery_endpoint_requires_cron_secret(monkeypatch):
    monkeypatch.setattr(router_module, "get_settings", fake_settings)

    response = await get("/internal/lead-sources/apollo/discovery-cycle")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_apollo_discovery_endpoint_returns_prepared_summary(monkeypatch):
    monkeypatch.setattr(router_module, "get_settings", fake_settings)

    class FakeApolloProvider:
        def __init__(self, **_kwargs):
            pass

        def fetch_leads(self, limit):
            assert limit == 25
            return [
                NormalizedLead(
                    person_name="Maya Founder",
                    title="Founder",
                    company_name="Metric AI",
                    company_url="https://metricai.example",
                    linkedin_url="https://linkedin.com/in/maya-founder",
                    country="United States",
                    employee_count=24,
                    industry="SaaS",
                    source="apollo",
                    source_id="person-1",
                    raw_source_data={"id": "person-1"},
                )
            ]

    monkeypatch.setattr(router_module, "ApolloLeadSourceProvider", FakeApolloProvider)

    response = await get(
        "/internal/lead-sources/apollo/discovery-cycle?limit=25",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["requested_limit"] == 25
    assert payload["fetched_count"] == 1
    assert payload["prepared_count"] == 1
    assert payload["duplicate_count"] == 0
    assert payload["qualified_count"] + payload["review_count"] + payload["rejected_count"] == 1
    assert payload["persistence"] is None


@pytest.mark.anyio
async def test_apollo_discovery_endpoint_persists_only_when_requested(monkeypatch):
    monkeypatch.setattr(router_module, "get_settings", fake_settings)
    calls = []

    class FakeApolloProvider:
        def __init__(self, **_kwargs):
            pass

        def fetch_leads(self, limit):
            return [
                NormalizedLead(
                    person_name="Maya Founder",
                    title="Founder",
                    company_name="Metric AI",
                    company_url="https://metricai.example",
                    linkedin_url="https://linkedin.com/in/maya-founder",
                    country="United States",
                    employee_count=24,
                    industry="SaaS",
                    source="apollo",
                    source_id="person-1",
                    raw_source_data={"id": "person-1"},
                )
            ]

    def fake_persist(settings, result):
        calls.append((settings, result))
        return {
            "inserted_count": 1,
            "updated_count": 0,
            "duplicate_count": 0,
            "lead_score_count": 1,
            "errors": [],
            "warnings": [],
        }

    monkeypatch.setattr(router_module, "ApolloLeadSourceProvider", FakeApolloProvider)
    monkeypatch.setattr(router_module, "_persist_apollo_discovery_result", fake_persist)

    dry_response = await get(
        "/internal/lead-sources/apollo/discovery-cycle?limit=25",
        headers={"Authorization": "Bearer test-cron-secret"},
    )
    assert dry_response.status_code == 200
    assert dry_response.json()["persistence"] is None
    assert calls == []

    persist_response = await get(
        "/internal/lead-sources/apollo/discovery-cycle?limit=25&persist=true",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert persist_response.status_code == 200
    assert persist_response.json()["persistence"]["inserted_count"] == 1
    assert len(calls) == 1


@pytest.mark.anyio
async def test_apollo_discovery_endpoint_returns_clear_missing_key(monkeypatch):
    monkeypatch.setattr(router_module, "get_settings", lambda: fake_settings(api_key=None))

    class MissingKeyProvider:
        def __init__(self, **_kwargs):
            pass

        def fetch_leads(self, _limit):
            raise ProviderAuthError("APOLLO_API_KEY is not configured.")

    monkeypatch.setattr(router_module, "ApolloLeadSourceProvider", MissingKeyProvider)

    response = await get(
        "/internal/lead-sources/apollo/discovery-cycle",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "APOLLO_API_KEY is not configured."


@pytest.mark.anyio
async def test_apollo_discovery_endpoint_returns_clear_403(monkeypatch):
    monkeypatch.setattr(router_module, "get_settings", fake_settings)

    class ForbiddenProvider:
        def __init__(self, **_kwargs):
            pass

        def fetch_leads(self, _limit):
            raise ProviderAuthError(
                "Apollo API rejected the request. Check APOLLO_API_KEY, plan access, or credits."
            )

    monkeypatch.setattr(router_module, "ApolloLeadSourceProvider", ForbiddenProvider)

    response = await get(
        "/internal/lead-sources/apollo/discovery-cycle",
        headers={"Authorization": "Bearer test-cron-secret"},
    )

    assert response.status_code == 502
    assert "plan access, or credits" in response.json()["detail"]
