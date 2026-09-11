from types import SimpleNamespace

from app.services.generic_outreach_drafts import (
    generate_primary_drafts_for_review_leads,
)


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, value):
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        self.client.inserts.setdefault(self.table_name, []).append(payload)
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        if self.operation == "insert":
            return SimpleNamespace(data=[{"id": f"{self.table_name}-1", **self.payload}])

        if self.table_name == "leads":
            rows = self.client.rows["leads"]
            for key, value in self.filters:
                rows = [row for row in rows if row.get(key) == value]
            return SimpleNamespace(data=rows[: getattr(self, "limit_value", len(rows))])

        if self.table_name == "lead_scores":
            lead_id = dict(self.filters).get("lead_id")
            return SimpleNamespace(data=self.client.rows["lead_scores"].get(lead_id, []))

        if self.table_name == "outreach_drafts":
            filters = dict(self.filters)
            rows = [
                row
                for row in self.client.rows["outreach_drafts"]
                if all(row.get(key) == value for key, value in filters.items())
            ]
            return SimpleNamespace(data=rows)

        return SimpleNamespace(data=[])


class FakeClient:
    def __init__(self):
        self.inserts = {}
        self.touched_tables = []
        self.rows = {
            "leads": [
                {
                    "id": "lead-review",
                    "person_name": "Maya Founder",
                    "title": "Founder",
                    "company_name": "Metric AI",
                    "company_url": "https://metricai.example",
                    "email": "maya@metricai.example",
                    "industry": "SaaS AI software",
                    "lead_source": "apollo_csv",
                    "status": "review",
                },
                {
                    "id": "lead-disqualified",
                    "person_name": "Pat Intern",
                    "title": "Intern",
                    "company_name": "Example University",
                    "company_url": "https://example.edu",
                    "industry": "Education",
                    "lead_source": "apollo_csv",
                    "status": "disqualified",
                },
            ],
            "lead_scores": {
                "lead-review": [
                    {
                        "score": 80,
                        "disposition": "Review",
                        "review_reasons": [
                            "Inferred ICP industry: SaaS/AI software",
                            "Strong decision-maker fit",
                        ],
                    }
                ]
            },
            "outreach_drafts": [],
        }

    def table(self, name):
        self.touched_tables.append(name)
        return FakeQuery(self, name)


def test_only_review_leads_are_eligible_and_disqualified_is_skipped():
    client = FakeClient()

    result = generate_primary_drafts_for_review_leads(client, dry_run=True)

    assert result.eligible_leads == 1
    assert result.email_drafts_created == 1
    assert result.linkedin_drafts_created == 1
    assert all(preview.lead_id == "lead-review" for preview in result.previews)


def test_existing_primary_draft_prevents_duplicate_channel():
    client = FakeClient()
    client.rows["outreach_drafts"] = [
        {
            "id": "draft-email",
            "lead_id": "lead-review",
            "sequence_step": 1,
            "channel": "email",
            "status": "draft",
        }
    ]

    result = generate_primary_drafts_for_review_leads(client, dry_run=False)

    assert result.skipped_existing == 1
    assert result.email_drafts_created == 0
    assert result.linkedin_drafts_created == 1
    assert len(client.inserts["outreach_drafts"]) == 1
    assert client.inserts["outreach_drafts"][0]["channel"] == "linkedin"


def test_email_and_linkedin_content_are_prospect_facing_and_pending_review():
    client = FakeClient()

    result = generate_primary_drafts_for_review_leads(client, dry_run=False)

    email = next(item for item in client.inserts["outreach_drafts"] if item["channel"] == "email")
    linkedin = next(
        item for item in client.inserts["outreach_drafts"] if item["channel"] == "linkedin"
    )
    assert email["status"] == "draft"
    assert linkedin["status"] == "draft"
    assert email["sequence_step"] == 1
    assert "Maya" in email["body"]
    assert "Metric AI" in email["body"]
    assert "review-only note" not in email["body"]
    assert "review-only note" not in linkedin["body"]
    assert "Datamart helps teams with AI agents" in email["body"]
    assert "AI agents" in email["body"]
    assert "Would it be worth a quick 10-minute conversation?" in email["body"]
    assert len(linkedin["body"]) < len(email["body"])
    assert "Datamart works on AI agents" in linkedin["body"]
    assert result.previews[0].body


def test_dry_run_does_not_insert_or_touch_sending_tables():
    client = FakeClient()

    generate_primary_drafts_for_review_leads(client, dry_run=True)

    assert client.inserts == {}
    assert "email_delivery_attempts" not in client.touched_tables
    assert "outreach_messages" not in client.touched_tables
    assert "lead_outreach" not in client.touched_tables
