from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import CurrentUser, require_user
from app.core.config import Settings
from app.main import app
from app.services import outreach_generation as service


def offline_settings(**overrides) -> Settings:
    values = {"supabase_url": None, "supabase_service_role_key": None,
              "aws_bearer_token_bedrock": None, "bedrock_model_id": None, **overrides}
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def reset_state() -> None:
    service.reset_fallback_outreach_state()


async def request_as(role: str, method: str, path: str, payload: dict | None = None,
                     settings: Settings | None = None):
    async def override_user() -> CurrentUser:
        return CurrentUser(id="user-1", email="sales@datamart.test", role=role)

    app.dependency_overrides[require_user] = override_user
    try:
        with patch("app.api.router.get_settings", return_value=settings or offline_settings()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                return await client.request(method, path, json=payload)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_approved_assigned_lead_can_generate_and_persist_outreach() -> None:
    response = await request_as("sales", "POST", "/outreach/generate", {"lead_id": "lead-01"})
    saved = await request_as("sales", "GET", "/outreach/lead-01")
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert saved.json()["latest_message"]["subject"] == response.json()["subject"]
    assert saved.json()["latest_message"]["body"] == response.json()["body"]


@pytest.mark.anyio
async def test_unapproved_lead_cannot_generate() -> None:
    response = await request_as("sales", "POST", "/outreach/generate", {"lead_id": "lead-02"})
    assert response.status_code == 400
    assert "approved for sales" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_disqualified_lead_cannot_generate() -> None:
    response = await request_as("sales", "POST", "/outreach/generate", {"lead_id": "lead-03"})
    assert response.status_code == 400
    assert "disqualified" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_suppressed_lead_cannot_generate() -> None:
    response = await request_as("sales", "POST", "/outreach/generate", {"lead_id": "lead-04"})
    assert response.status_code == 403
    assert "suppressed" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_bedrock_result_and_evidence_references_persist_without_live_aws() -> None:
    generated = {"subject": "Northstar question", "body": "Hi Avery,\n\nWould a brief conversation be useful?",
        "provider": "bedrock", "model": "test-model", "evidence_refs": ["src-1"],
        "evidence_coverage": "full", "grounding_warnings": [], "generated_at": "2026-09-03T00:00:00Z"}
    settings = offline_settings(aws_bearer_token_bedrock="test-token", bedrock_model_id="test-model")
    with patch("app.services.outreach_generation.BedrockClient.generate_outreach_message", return_value=generated):
        response = await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-01"}, settings)
    current = await request_as("manager", "GET", "/outreach/lead-01")
    assert response.status_code == 200
    assert current.json()["latest_message"]["evidence_refs"] == ["src-1"]
    assert current.json()["latest_message"]["provider"] == "bedrock"
    assert current.json()["latest_message"]["model"] == "test-model"


@pytest.mark.anyio
async def test_generation_rejects_unstored_evidence_reference() -> None:
    generated = {"subject": "Question", "body": "Hi Avery, would a conversation be useful?",
        "provider": "bedrock", "model": "test", "evidence_refs": ["invented-source"],
        "grounding_warnings": [], "generated_at": "2026-09-03T00:00:00Z"}
    settings = offline_settings(aws_bearer_token_bedrock="token", bedrock_model_id="test")
    with patch("app.services.outreach_generation.BedrockClient.generate_outreach_message", return_value=generated):
        response = await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-01"}, settings)
    assert response.status_code == 400
    assert "not stored" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_factual_generation_remains_evidence_grounded() -> None:
    with patch("app.services.outreach_generation.OutreachDraftEngine.draft", return_value={
        "subject": "Funding news", "body": "I noticed you launched a $20M funding round",
        "evidence_ids": ["src-5"], "channel": "email"}):
        response = await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-05"})
    assert response.status_code == 400
    assert "claim" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_insufficient_evidence_produces_safe_generic_copy(monkeypatch) -> None:
    monkeypatch.setitem(service._FALLBACK_EVIDENCE, "lead-01", [])
    response = await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-01"})
    assert response.status_code == 200
    assert response.json()["evidence_refs"] == []
    assert response.json()["grounding_status"] == "insufficient_evidence_generic"
    assert "funding" not in response.json()["body"].lower()


@pytest.mark.anyio
async def test_existing_draft_can_be_retrieved() -> None:
    await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-01"})
    response = await request_as("manager", "GET", "/outreach/lead-01")
    assert response.status_code == 200
    assert response.json()["lead_outreach"]["status"] == "draft"
    assert response.json()["latest_message"]["status"] == "draft"
    assert response.json()["evidence"][0]["source_url"].startswith("https://")


@pytest.mark.anyio
async def test_manual_subject_and_body_edits_persist_with_events() -> None:
    await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-01"})
    response = await request_as("manager", "POST", "/outreach/lead-01/save",
                                {"subject": "Edited subject", "body": "Hi Avery,\n\nCould we talk?"})
    current = await request_as("manager", "GET", "/outreach/lead-01")
    assert response.status_code == 200
    assert current.json()["latest_message"]["subject"] == "Edited subject"
    assert current.json()["latest_message"]["body"] == "Hi Avery,\n\nCould we talk?"
    event_types = [item["event_type"] for item in current.json()["events"]]
    assert "outreach_edited" in event_types
    assert "outreach_saved" in event_types


@pytest.mark.anyio
async def test_regeneration_updates_draft_and_records_event() -> None:
    await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-01"})
    response = await request_as("manager", "POST", "/outreach/lead-01/regenerate", {})
    assert response.status_code == 200
    assert any(item["event_type"] == "outreach_regenerated" for item in response.json()["events"])


@pytest.mark.anyio
async def test_sent_message_cannot_be_edited_or_regenerated() -> None:
    await request_as("manager", "POST", "/outreach/generate", {"lead_id": "lead-01"})
    service._FALLBACK_STATE["lead-01"]["latest_message"]["status"] = "sent"
    service._FALLBACK_STATE["lead-01"]["lead_outreach"]["status"] = "sent"
    edit = await request_as("manager", "POST", "/outreach/lead-01/save", {"subject": "No", "body": "No"})
    regenerate = await request_as("manager", "POST", "/outreach/lead-01/regenerate", {})
    assert edit.status_code == 400
    assert regenerate.status_code == 400
    assert "sent or finalized" in edit.json()["detail"].lower()


@pytest.mark.anyio
async def test_role_authorization_is_enforced() -> None:
    response = await request_as("analyst", "POST", "/outreach/generate", {"lead_id": "lead-01"})
    assert response.status_code == 403


@pytest.mark.anyio
async def test_sales_user_cannot_access_unassigned_lead(monkeypatch) -> None:
    monkeypatch.setitem(service._FALLBACK_LEADS["lead-01"], "assigned_to", "another-user")
    response = await request_as("sales", "GET", "/outreach/lead-01")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_outreach_list_only_includes_eligible_accessible_leads() -> None:
    response = await request_as("sales", "GET", "/outreach")
    ids = {item["id"] for item in response.json()}
    assert "lead-01" in ids
    assert "lead-02" not in ids
    assert "lead-03" not in ids


@pytest.mark.anyio
async def test_suppression_is_returned_in_retrieval_and_list() -> None:
    detail = await request_as("manager", "GET", "/outreach/lead-04")
    listing = await request_as("manager", "GET", "/outreach")
    suppressed = next(item for item in listing.json() if item["id"] == "lead-04")
    assert detail.json()["suppressed"] is True
    assert suppressed["suppressed"] is True


def test_configured_persistence_writes_phase_a_message_metadata_and_audit() -> None:
    writes: list[tuple[str, dict]] = []

    class Query:
        def __init__(self, table: str): self.table, self.operation, self.payload = table, "select", {}
        def select(self, *_args): return self
        def eq(self, *_args): return self
        def single(self): return self
        def update(self, payload): self.operation, self.payload = "update", payload; return self
        def insert(self, payload): self.operation, self.payload = "insert", payload; return self
        def execute(self):
            if self.operation in {"insert", "update"}: writes.append((self.table, self.payload))
            if self.table == "outreach_sequences": return type("R", (), {"data": {"id": "sequence-db"}})()
            if self.table == "outreach_sequence_steps": return type("R", (), {"data": {"id": "step-db"}})()
            if self.table == "lead_outreach" and self.operation == "insert":
                return type("R", (), {"data": [{"id": "outreach-db", **self.payload}]})()
            if self.table == "outreach_messages" and self.operation == "insert":
                return type("R", (), {"data": [{"id": "message-db", **self.payload}]})()
            return type("R", (), {"data": []})()

    class Client:
        def table(self, name: str): return Query(name)

    settings = offline_settings(supabase_url="https://project.supabase.co", supabase_service_role_key="secret")
    final_state = {"lead_outreach": {"id": "outreach-db", "status": "draft"},
                   "latest_message": {"id": "message-db", "status": "draft"}, "events": []}
    draft = {"subject": "Subject", "body": "Body", "provider": "bedrock", "model": "test-model",
             "evidence_refs": ["evidence-1"], "grounding_status": "full",
             "grounding_warnings": [], "generated_at": "2026-09-03T00:00:00Z"}
    lead = {"id": "lead-db", "email": "lead@example.com"}
    with patch("app.services.outreach_generation._client", return_value=Client()), \
         patch("app.services.outreach_generation._db_state", side_effect=[None, final_state]):
        service._db_persist(settings, lead, draft, "actor-db", False)

    message = next(payload for table, payload in writes if table == "outreach_messages")
    assert message["subject"] == "Subject"
    assert message["body"] == "Body"
    assert message["provider_response"]["evidence_refs"] == ["evidence-1"]
    assert message["generation_provider"] == "bedrock"
    assert message["generation_model"] == "test-model"
    assert message["idempotency_key"]
    assert any(table == "outreach_events" for table, _payload in writes)
    assert any(table == "audit_log" for table, _payload in writes)
