from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.main import app


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, value):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.filters.append((key, set(values)))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        if self.operation == "insert":
            row = {"id": f"{self.table}-{len(self.client.rows.setdefault(self.table, [])) + 1}", **self.payload}
            self.client.rows.setdefault(self.table, []).append(row)
            self.client.inserts.setdefault(self.table, []).append(row)
            return SimpleNamespace(data=[row])

        if self.operation == "update":
            if self.table != "outreach_drafts":
                return SimpleNamespace(data=[])
            draft_id = dict(self.filters).get("id")
            row = next(
                (item for item in self.client.rows["outreach_drafts"] if item["id"] == draft_id),
                None,
            )
            if not row:
                return SimpleNamespace(data=[])
            row.update(self.payload)
            return SimpleNamespace(data=[row])

        rows = self.client.rows.get(self.table, [])
        for key, value in self.filters:
            if isinstance(value, set):
                rows = [row for row in rows if row.get(key) in value]
            else:
                rows = [row for row in rows if row.get(key) == value]
        return SimpleNamespace(data=rows[: getattr(self, "limit_value", len(rows))])


class FakeClient:
    def __init__(self):
        self.rows = {
            "leads": [
                {
                    "id": "lead-review",
                    "person_name": "Maya Founder",
                    "title": "Founder",
                    "company_name": "Metric AI",
                    "email": "maya@metricai.example",
                    "phone": "+15555550100",
                    "linkedin_url": "https://linkedin.com/in/maya",
                    "company_url": "https://metricai.example",
                    "country": "United States",
                    "industry": "SaaS AI software",
                    "employee_count": 24,
                    "lead_source": "apollo_csv",
                    "source_id": "contact-1",
                    "status": "review",
                    "created_at": "2026-09-11T00:00:00Z",
                    "source_captured_at": "2026-09-11T00:00:00Z",
                },
                {
                    "id": "lead-disqualified",
                    "person_name": "Pat Intern",
                    "lead_source": "apollo_csv",
                    "status": "disqualified",
                },
            ],
            "lead_scores": [
                {
                    "lead_id": "lead-review",
                    "score": 80,
                    "disposition": "Review",
                    "tier": "Tier 1",
                    "persona": "Founder",
                    "hard_stops": [],
                    "review_reasons": ["Strong decision-maker fit"],
                    "evaluations": [{"label": "Decision-maker", "outcome": "matched"}],
                    "intent_score": 0,
                    "intent_level": "low",
                    "intent_reasons": [],
                    "scored_at": "2026-09-11T01:00:00Z",
                }
            ],
            "outreach_drafts": [
                {
                    "id": "draft-email-1",
                    "lead_id": "lead-review",
                    "channel": "email",
                    "subject": "Quick question",
                    "body": "Hi Maya",
                    "status": "draft",
                    "sequence_step": 1,
                    "evidence_ids": [],
                    "created_by": None,
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "review_notes": None,
                    "created_at": "2026-09-11T02:00:00Z",
                    "updated_at": "2026-09-11T02:00:00Z",
                },
                {
                    "id": "draft-linkedin-4",
                    "lead_id": "lead-review",
                    "channel": "linkedin",
                    "subject": None,
                    "body": "Close the loop?",
                    "status": "draft",
                    "sequence_step": 4,
                    "evidence_ids": [],
                    "created_by": None,
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "review_notes": None,
                    "created_at": "2026-09-11T02:00:00Z",
                    "updated_at": "2026-09-11T02:00:00Z",
                },
            ],
            "email_delivery_attempts": [],
            "inbound_reply_events": [],
            "audit_log": [],
        }
        self.inserts = {}

    def table(self, name):
        return FakeQuery(self, name)


async def request_as(role: str, method: str, path: str, json: dict | None = None):
    async def override_user() -> CurrentUser:
        return CurrentUser(id="reviewer-1", email="reviewer@datamart.test", role=role)

    app.dependency_overrides[require_user] = override_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_review_workspace_endpoint_returns_grouped_drafts_and_filters_defaults():
    fake = FakeClient()
    with patch("app.api.router._backend_client", return_value=fake):
        response = await request_as(
            "manager",
            "GET",
            "/leads/review-workspace?source=apollo_csv&status=review",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "apollo_csv"
    assert len(body["leads"]) == 1
    lead = body["leads"][0]
    assert lead["id"] == "lead-review"
    assert lead["latest_score"]["score"] == 80
    assert lead["outreach_drafts"]["email"]["step_1"]["id"] == "draft-email-1"
    assert lead["outreach_drafts"]["linkedin"]["step_4"]["id"] == "draft-linkedin-4"


@pytest.mark.anyio
async def test_review_workspace_endpoint_can_exclude_drafts():
    fake = FakeClient()
    with patch("app.api.router._backend_client", return_value=fake):
        response = await request_as(
            "sales",
            "GET",
            "/leads/review-workspace?include_drafts=false",
        )

    assert response.status_code == 200
    assert response.json()["leads"][0]["outreach_drafts"]["email"]["step_1"] is None


@pytest.mark.anyio
async def test_draft_review_patch_updates_status_only_and_does_not_send():
    fake = FakeClient()
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router._send_approved_email") as send,
    ):
        response = await request_as(
            "manager",
            "PATCH",
            "/outreach-drafts/draft-email-1/review",
            {"action": "needs_edit", "review_notes": "Tighten opening line"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_edit"
    assert body["review_notes"] == "Tighten opening line"
    assert send.call_count == 0


@pytest.mark.anyio
async def test_manual_send_endpoint_marks_manual_sent_without_sending():
    fake = FakeClient()
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router._send_approved_email") as send,
    ):
        response = await request_as(
            "sales",
            "PATCH",
            "/outreach-drafts/draft-email-1/manual-send",
            {"review_notes": "Sent from personal inbox"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "manual_sent"
    assert body["review_notes"] == "Sent from personal inbox"
    assert send.call_count == 0


@pytest.mark.anyio
async def test_next_followup_endpoint_blocks_when_previous_is_draft():
    fake = FakeClient()
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router._send_approved_email") as send,
    ):
        response = await request_as(
            "manager",
            "POST",
            "/leads/lead-review/outreach/next-followup-draft",
            {"channel": "email", "source": "apollo_csv"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["results"]["email"]["created"] is False
    assert body["results"]["email"]["reason"] == "previous_step_not_sent_or_approved"
    assert "outreach_drafts" not in fake.inserts
    assert send.call_count == 0


@pytest.mark.anyio
async def test_next_followup_endpoint_creates_next_draft_after_manual_send():
    fake = FakeClient()
    fake.rows["outreach_drafts"][0]["status"] = "manual_sent"
    fake.rows["outreach_drafts"] = [fake.rows["outreach_drafts"][0]]
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router._send_approved_email") as send,
    ):
        response = await request_as(
            "sales",
            "POST",
            "/leads/lead-review/outreach/next-followup-draft",
            {"channel": "email", "source": "apollo_csv"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["results"]["email"]["created"] is True
    assert body["results"]["email"]["sequence_step"] == 2
    assert fake.inserts["outreach_drafts"][0]["status"] == "draft"
    assert send.call_count == 0


@pytest.mark.anyio
async def test_next_followup_endpoint_ignores_terminal_future_drafts():
    fake = FakeClient()
    fake.rows["outreach_drafts"][0]["status"] = "manual_sent"
    fake.rows["outreach_drafts"][1]["channel"] = "email"
    fake.rows["outreach_drafts"][1]["sequence_step"] = 2
    fake.rows["outreach_drafts"][1]["status"] = "rejected"
    with (
        patch("app.api.router._backend_client", return_value=fake),
        patch("app.api.router._send_approved_email") as send,
    ):
        response = await request_as(
            "sales",
            "POST",
            "/leads/lead-review/outreach/next-followup-draft",
            {"channel": "email", "source": "apollo_csv"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["results"]["email"]["created"] is True
    assert body["results"]["email"]["sequence_step"] == 2
    assert fake.inserts["outreach_drafts"][0]["status"] == "draft"
    assert send.call_count == 0


@pytest.mark.anyio
async def test_manager_cannot_approve_draft_status():
    response = await request_as(
        "manager",
        "PATCH",
        "/outreach-drafts/draft-email-1/review",
        {"action": "approve", "review_notes": "Looks good"},
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_review_workspace_rejects_missing_auth_when_configured():
    async def reject_user() -> CurrentUser:
        raise HTTPException(status_code=401, detail="Authentication required")

    app.dependency_overrides[require_user] = reject_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/leads/review-workspace")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
