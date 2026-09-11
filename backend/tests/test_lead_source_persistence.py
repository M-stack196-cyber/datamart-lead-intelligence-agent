from types import SimpleNamespace
import pytest

from app.lead_sources import NormalizedLead
from app.services.lead_source_ingestion import prepare_and_score_leads
from app.services.lead_source_persistence import (
    SUPABASE_PERSISTENCE_NOT_CONFIGURED,
    persist_scored_leads,
    service_role_client,
)


class FakeQuery:
    def __init__(self, client, table_name, operation=None, payload=None):
        self.client = client
        self.table_name = table_name
        self.operation = operation
        self.payload = payload
        self.filters = []

    def select(self, value):
        self.operation = "select"
        self.client.calls.append((self.table_name, "select", value))
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        self.client.inserts.setdefault(self.table_name, []).append(payload)
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        self.client.updates.setdefault(self.table_name, []).append(payload)
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        return self

    def execute(self):
        if self.operation == "select":
            if self.table_name == "icp_versions":
                return SimpleNamespace(data=[{"id": "icp-version-1", "version": 2}])
            rows = self.client.select_rows.get((self.table_name, tuple(self.filters)), [])
            return SimpleNamespace(data=rows)

        if self.operation == "insert":
            if self.table_name == "imports":
                return SimpleNamespace(data=[{"id": "import-1", **self.payload}])
            if self.table_name == "leads":
                row = {"id": f"lead-{len(self.client.inserts.get('leads', []))}", **self.payload}
                return SimpleNamespace(data=[row])
            if self.table_name == "lead_scores":
                return SimpleNamespace(data=[{"id": "score-1", **self.payload}])
            return SimpleNamespace(data=[self.payload])

        if self.operation == "update":
            if self.table_name == "leads":
                return SimpleNamespace(data=[{"id": "existing-lead", **self.payload}])
            return SimpleNamespace(data=[self.payload])

        return SimpleNamespace(data=[])


class FakeClient:
    def __init__(self):
        self.inserts = {}
        self.updates = {}
        self.calls = []
        self.select_rows = {}

    def table(self, name):
        return FakeQuery(self, name)


def scored_result(source_id="contact-1"):
    lead = NormalizedLead(
        person_name="Maya Founder",
        title="Founder",
        company_name="Metric AI",
        company_url="https://metricai.example",
        linkedin_url="https://linkedin.com/in/maya-founder",
        email="Maya@MetricAI.example",
        phone="+15555550100",
        country="United States",
        employee_count=24,
        industry="SaaS AI software",
        source="apollo_csv",
        source_id=source_id,
        raw_source_data={"Apollo Contact Id": source_id},
    )
    return prepare_and_score_leads([lead])


def test_persist_scored_apollo_csv_lead_inserts_lead_and_score_payloads():
    client = FakeClient()

    result = persist_scored_leads(client, scored_result(), file_name="apollo.csv")

    lead_payload = client.inserts["leads"][0]
    score_payload = client.inserts["lead_scores"][0]
    assert result.inserted_count == 1
    assert result.updated_count == 0
    assert lead_payload["lead_source"] == "apollo_csv"
    assert lead_payload["source_id"] == "contact-1"
    assert lead_payload["person_name"] == "Maya Founder"
    assert lead_payload["email"] == "maya@metricai.example"
    assert lead_payload["phone"] == "+15555550100"
    assert lead_payload["status"] == "review"
    assert lead_payload["raw_source_data"]["source"] == "apollo_csv"
    assert lead_payload["raw_source_data"]["pipeline_status"] == "needs_review"
    assert score_payload["lead_id"] == "lead-1"
    assert score_payload["icp_version_id"] == "icp-version-1"
    assert score_payload["score"] > 40
    assert isinstance(score_payload["review_reasons"], list)


def test_duplicate_lead_updates_existing_row_without_insert_duplicate():
    client = FakeClient()
    client.select_rows[
        ("leads", (("email", "maya@metricai.example"),))
    ] = [
        {
            "id": "existing-lead",
            "email": "maya@metricai.example",
            "raw_source_data": {"existing": True},
        }
    ]

    result = persist_scored_leads(client, scored_result(), file_name="apollo.csv")

    assert result.inserted_count == 0
    assert result.updated_count == 1
    assert client.inserts.get("leads") is None
    assert client.updates["leads"][0]["raw_source_data"]["existing"] is True
    assert client.inserts["lead_scores"][0]["lead_id"] == "existing-lead"


def test_missing_supabase_config_raises_clear_error():
    with pytest.raises(RuntimeError, match="Supabase persistence is not configured"):
        service_role_client(
            SimpleNamespace(supabase_url=None, supabase_service_role_key=None)
        )

    assert SUPABASE_PERSISTENCE_NOT_CONFIGURED.endswith("SUPABASE_SERVICE_ROLE_KEY.")
