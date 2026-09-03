from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.main import app


async def request_as(role: str, method: str, path: str, json: dict):
    async def override_user() -> CurrentUser:
        return CurrentUser(id="reviewer-1", email="reviewer@datamart.test", role=role)

    app.dependency_overrides[require_user] = override_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_manager_can_generate_but_cannot_approve_outreach() -> None:
    with patch(
        "app.api.router._generate_outreach_draft",
        return_value={"id": "draft-1", "status": "draft"},
    ):
        generated = await request_as(
            "manager",
            "POST",
            "/outreach/drafts/generate",
            {"lead_id": "lead-1", "channel": "email"},
        )

    approval = await request_as(
        "manager",
        "POST",
        "/outreach/drafts/draft-1/review",
        {"action": "approved", "review_notes": "Grounded and ready"},
    )

    assert generated.status_code == 200
    assert generated.json()["status"] == "draft"
    assert approval.status_code == 403
    assert approval.json()["detail"] == "Admin role required for outreach approval"


@pytest.mark.anyio
async def test_admin_can_approve_exact_reviewed_draft() -> None:
    with patch(
        "app.api.router._review_outreach_draft",
        return_value={"id": "draft-1", "status": "approved"},
    ):
        response = await request_as(
            "admin",
            "POST",
            "/outreach/drafts/draft-1/review",
            {"action": "approved", "review_notes": "Evidence verified"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"


@pytest.mark.anyio
async def test_email_endpoint_requires_literal_confirmation_and_never_sends_implicitly() -> None:
    with patch(
        "app.api.router._send_approved_email",
        return_value={"status": "sent", "provider_message_id": "gmail-1"},
    ) as send:
        rejected = await request_as(
            "sales",
            "POST",
            "/outreach/drafts/draft-1/send-email",
            {"confirm": False},
        )
        accepted = await request_as(
            "sales",
            "POST",
            "/outreach/drafts/draft-1/send-email",
            {"confirm": True},
        )

    assert rejected.status_code == 422
    assert accepted.status_code == 200
    assert send.call_count == 1
