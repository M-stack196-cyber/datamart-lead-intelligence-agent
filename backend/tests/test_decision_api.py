import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.main import app


@pytest.mark.anyio
async def test_decision_route_combines_icp_and_intent_into_approval_status() -> None:
    app.dependency_overrides[require_user] = lambda: CurrentUser(
        id="test-user", email="sales@datamart.test", role="sales"
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/decision/lead",
                json={
                    "lead": {"company_name": "Datamart", "title": "Founder", "person_name": "Aisha Rafiq"},
                    "icp_score": 82,
                    "intent_score": 84,
                    "evidence_urls": ["https://example.com/hiring"],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["score"] >= 80
