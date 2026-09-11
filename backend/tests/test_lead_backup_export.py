import csv
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.main import app
from app.services.lead_backup_export import build_lead_backup_csv, build_lead_backup_preview


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = []
        self.limit_value = None

    def select(self, value):
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
        rows = list(self.client.rows.get(self.table, []))
        for key, value in self.filters:
            if isinstance(value, set):
                rows = [row for row in rows if row.get(key) in value]
            else:
                rows = [row for row in rows if row.get(key) == value]
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return SimpleNamespace(data=rows)


class FakeClient:
    def __init__(self):
        self.rows = {
            "leads": [
                {
                    "id": "lead-1",
                    "lead_source": "apollo_csv",
                    "source_id": "apollo-1",
                    "status": "review",
                    "person_name": "Maya Founder",
                    "title": "Founder",
                    "company_name": "Metric AI",
                    "email": "maya@metric.example",
                    "phone": "+15555550100",
                    "linkedin_url": "https://linkedin.com/in/maya",
                    "company_url": "https://metric.example",
                    "country": "United States",
                    "industry": "SaaS AI software",
                    "employee_count": 24,
                    "annual_revenue": 1200000,
                    "created_at": "2026-09-11T00:00:00Z",
                    "source_captured_at": "2026-09-11T00:05:00Z",
                },
                {
                    "id": "lead-2",
                    "lead_source": "vibe",
                    "source_id": "vibe-1",
                    "status": "disqualified",
                    "person_name": "No Draft",
                    "company_name": "Other Co",
                    "created_at": "2026-09-10T00:00:00Z",
                },
            ],
            "lead_scores": [
                {
                    "lead_id": "lead-1",
                    "score": 80,
                    "disposition": "Review",
                    "tier": "Tier 1",
                    "persona": "Founder",
                    "review_reasons": ["Strong decision-maker fit"],
                    "hard_stops": [],
                    "evaluations": [{"label": "Decision-maker", "outcome": "matched"}],
                    "intent_score": 20,
                    "intent_level": "low",
                    "intent_reasons": ["No explicit intent found"],
                    "scored_at": "2026-09-11T01:00:00Z",
                },
                {
                    "lead_id": "lead-1",
                    "score": 70,
                    "disposition": "Older",
                    "scored_at": "2026-09-10T01:00:00Z",
                },
            ],
            "outreach_drafts": [
                {
                    "id": "draft-email-1",
                    "lead_id": "lead-1",
                    "channel": "email",
                    "sequence_step": 1,
                    "subject": "Quick question",
                    "body": "Hi Maya with a deliberately long full email body for CSV backup",
                    "status": "approved",
                    "review_notes": "Marked as manually sent outside the system.",
                    "reviewed_at": "2026-09-11T02:00:00Z",
                },
                {
                    "id": "draft-linkedin-2",
                    "lead_id": "lead-1",
                    "channel": "linkedin",
                    "sequence_step": 2,
                    "subject": None,
                    "body": "Quick bump with full LinkedIn text for CSV backup",
                    "status": "draft",
                    "review_notes": "",
                    "reviewed_at": None,
                },
            ],
            "inbound_reply_events": [
                {
                    "id": "reply-1",
                    "lead_id": "lead-1",
                    "received_at": "2026-09-11T03:00:00Z",
                }
            ],
            "email_delivery_attempts": [
                {
                    "id": "attempt-1",
                    "lead_id": "lead-1",
                    "outreach_draft_id": "draft-email-1",
                    "status": "sent",
                }
            ],
        }

    def table(self, name):
        return FakeQuery(self, name)


def csv_rows(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(content)))


def test_lead_backup_csv_includes_lead_score_drafts_reply_and_send_counts():
    export = build_lead_backup_csv(FakeClient(), source="apollo_csv", status="review")

    rows = csv_rows(export.content)
    assert export.filename.startswith("datamart-lead-backup-apollo_csv-")
    assert len(rows) == 1
    row = rows[0]
    assert row["lead_id"] == "lead-1"
    assert row["person_name"] == "Maya Founder"
    assert row["company_name"] == "Metric AI"
    assert row["icp_score"] == "80"
    assert row["review_reasons"] == '["Strong decision-maker fit"]'
    assert row["total_drafts"] == "2"
    assert row["email_step_1_subject"] == "Quick question"
    assert row["email_step_1_body"] == "Hi Maya with a deliberately long full email body for CSV backup"
    assert row["email_step_1_status"] == "approved"
    assert row["linkedin_step_2_body"] == "Quick bump with full LinkedIn text for CSV backup"
    assert row["lead_replied"] == "True"
    assert row["latest_reply_at"] == "2026-09-11T03:00:00Z"
    assert row["manually_sent_count"] == "1"
    assert row["system_sent_count"] == "1"


def test_lead_backup_csv_source_and_status_filters_work():
    export = build_lead_backup_csv(FakeClient(), source="vibe", status="disqualified")

    rows = csv_rows(export.content)
    assert len(rows) == 1
    assert rows[0]["lead_id"] == "lead-2"
    assert rows[0]["total_drafts"] == "0"
    assert rows[0]["email_step_1_body"] == ""


def test_lead_backup_preview_returns_summary_without_full_body_fields():
    preview = build_lead_backup_preview(FakeClient(), source="apollo_csv", status="review")

    assert preview["source"] == "apollo_csv"
    assert preview["status"] == "review"
    assert preview["total"] == 1
    assert preview["generated_at"]
    row = preview["leads"][0]
    assert row["lead_id"] == "lead-1"
    assert row["company_name"] == "Metric AI"
    assert row["icp_score"] == "80"
    assert row["review_reasons"] == ["Strong decision-maker fit"]
    assert row["total_drafts"] == 2
    assert row["approved_count"] == 1
    assert row["draft_count"] == 1
    assert row["lead_replied"] is True
    assert row["email_step_1_status"] == "approved"
    assert row["linkedin_step_2_status"] == "draft"
    assert "email_step_1_body" not in row
    assert "linkedin_step_2_body" not in row


@pytest.mark.anyio
async def test_lead_backup_endpoint_requires_auth():
    async def reject_user() -> CurrentUser:
        raise HTTPException(status_code=401, detail="Authentication required")

    app.dependency_overrides[require_user] = reject_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/leads/backup-export")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.anyio
async def test_lead_backup_preview_endpoint_requires_auth():
    async def reject_user() -> CurrentUser:
        raise HTTPException(status_code=401, detail="Authentication required")

    app.dependency_overrides[require_user] = reject_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/leads/backup-preview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


async def request_as(role: str, path: str):
    async def override_user() -> CurrentUser:
        return CurrentUser(id="user-1", email="user@datamart.test", role=role)

    app.dependency_overrides[require_user] = override_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_lead_backup_endpoint_returns_csv_attachment_and_does_not_send():
    with (
        patch("app.api.router._backend_client", return_value=FakeClient()),
        patch("app.api.router._send_approved_email") as send,
    ):
        response = await request_as(
            "manager",
            "/leads/backup-export?source=apollo_csv&status=review&limit=100&format=csv",
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]
    assert "datamart-lead-backup-apollo_csv-" in response.headers["content-disposition"]
    assert csv_rows(response.text)[0]["lead_id"] == "lead-1"
    assert "deliberately long full email body" in response.text
    assert send.call_count == 0


@pytest.mark.anyio
async def test_lead_backup_preview_endpoint_returns_json_and_does_not_send():
    with (
        patch("app.api.router._backend_client", return_value=FakeClient()),
        patch("app.api.router._send_approved_email") as send,
    ):
        response = await request_as(
            "manager",
            "/leads/backup-preview?source=apollo_csv&status=review&limit=100",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["leads"][0]["lead_id"] == "lead-1"
    assert body["leads"][0]["total_drafts"] == 2
    assert body["leads"][0]["lead_replied"] is True
    assert "email_step_1_body" not in body["leads"][0]
    assert send.call_count == 0


@pytest.mark.anyio
async def test_sales_role_cannot_download_backup_export():
    response = await request_as("sales", "/leads/backup-export")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_sales_role_cannot_view_backup_preview():
    response = await request_as("sales", "/leads/backup-preview")

    assert response.status_code == 403
