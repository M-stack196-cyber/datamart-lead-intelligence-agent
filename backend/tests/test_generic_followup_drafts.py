from types import SimpleNamespace

import pytest

from app.services.generic_outreach_drafts import generate_followup_drafts_for_review_leads


INTERNAL_WORDS = ("review-only", "approval", "approved", "draft")


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
            rows = self.client.rows["outreach_drafts"]
            for key, value in self.filters:
                rows = [row for row in rows if row.get(key) == value]
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


def add_previous(client, *, step=1, channel="email", status="draft"):
    client.rows["outreach_drafts"].append(
        {
            "id": f"{channel}-{step}",
            "lead_id": "lead-review",
            "sequence_step": step,
            "channel": channel,
            "status": status,
        }
    )


def add_primary_pair(client):
    add_previous(client, step=1, channel="email", status="approved")
    add_previous(client, step=1, channel="linkedin", status="approved")


def test_followup_step_must_be_two_three_or_four():
    with pytest.raises(ValueError, match="Follow-up step must be 2, 3, or 4"):
        generate_followup_drafts_for_review_leads(FakeClient(), followup_step=5)


def test_disqualified_leads_are_skipped_and_followup_one_requires_primary():
    client = FakeClient()
    add_previous(client, step=1, channel="email", status="approved")

    result = generate_followup_drafts_for_review_leads(client, followup_step=2, dry_run=True)

    assert result.eligible_leads == 1
    assert result.email_drafts_created == 1
    assert result.linkedin_drafts_created == 0
    assert result.skipped_missing_previous == 1


def test_followup_two_requires_followup_one():
    client = FakeClient()
    add_previous(client, step=1, channel="email", status="approved")

    result = generate_followup_drafts_for_review_leads(
        client,
        followup_step=3,
        create_linkedin=False,
        dry_run=True,
    )

    assert result.email_drafts_created == 0
    assert result.skipped_missing_previous == 1

    add_previous(client, step=2, channel="email", status="approved")
    result = generate_followup_drafts_for_review_leads(
        client,
        followup_step=3,
        create_linkedin=False,
        dry_run=True,
    )
    assert result.email_drafts_created == 1


def test_followup_three_requires_followup_two():
    client = FakeClient()
    add_previous(client, step=2, channel="email", status="approved")

    result = generate_followup_drafts_for_review_leads(
        client,
        followup_step=4,
        create_linkedin=False,
        dry_run=True,
    )

    assert result.email_drafts_created == 0
    assert result.skipped_missing_previous == 1

    add_previous(client, step=3, channel="email", status="approved")
    result = generate_followup_drafts_for_review_leads(
        client,
        followup_step=4,
        create_linkedin=False,
        dry_run=True,
    )
    assert result.email_drafts_created == 1


def test_existing_same_step_channel_prevents_duplicate():
    client = FakeClient()
    add_previous(client, step=1, channel="email", status="approved")
    add_previous(client, step=2, channel="email")

    result = generate_followup_drafts_for_review_leads(
        client,
        followup_step=2,
        create_linkedin=False,
        dry_run=False,
    )

    assert result.email_drafts_created == 0
    assert result.skipped_existing == 1
    assert client.inserts == {}


def test_rerunning_same_followup_step_skips_email_and_linkedin_without_insert():
    client = FakeClient()
    add_primary_pair(client)
    add_previous(client, step="4", channel="email")
    add_previous(client, step="4", channel="linkedin")

    result = generate_followup_drafts_for_review_leads(client, followup_step=4, dry_run=True)

    assert result.skipped_existing == 2
    assert result.email_drafts_created == 0
    assert result.linkedin_drafts_created == 0
    assert result.errors == []
    assert client.inserts == {}

    result = generate_followup_drafts_for_review_leads(client, followup_step=4, dry_run=False)

    assert result.skipped_existing == 2
    assert result.email_drafts_created == 0
    assert result.linkedin_drafts_created == 0
    assert result.errors == []
    assert client.inserts == {}


def test_duplicate_prevention_is_separate_for_email_and_linkedin():
    client = FakeClient()
    add_primary_pair(client)
    add_previous(client, step=2, channel="email")

    result = generate_followup_drafts_for_review_leads(client, followup_step=2, dry_run=False)

    assert result.skipped_existing == 1
    assert result.email_drafts_created == 0
    assert result.linkedin_drafts_created == 1
    assert len(client.inserts["outreach_drafts"]) == 1
    assert client.inserts["outreach_drafts"][0]["channel"] == "linkedin"


def test_rejected_previous_step_blocks_followup():
    client = FakeClient()
    add_previous(client, step=1, channel="email", status="rejected")

    result = generate_followup_drafts_for_review_leads(
        client,
        followup_step=2,
        create_linkedin=False,
        dry_run=True,
    )

    assert result.email_drafts_created == 0
    assert result.skipped_missing_previous == 1


def test_followup_email_and_linkedin_are_inserted_as_drafts_without_internal_words():
    client = FakeClient()
    add_previous(client, step=1, channel="email", status="approved")
    add_previous(client, step=1, channel="linkedin", status="approved")

    result = generate_followup_drafts_for_review_leads(client, followup_step=2, dry_run=False)

    email = next(item for item in client.inserts["outreach_drafts"] if item["channel"] == "email")
    linkedin = next(
        item for item in client.inserts["outreach_drafts"] if item["channel"] == "linkedin"
    )
    assert result.email_drafts_created == 1
    assert result.linkedin_drafts_created == 1
    assert email["sequence_step"] == 2
    assert linkedin["sequence_step"] == 2
    assert email["status"] == "draft"
    assert linkedin["status"] == "draft"
    assert "Would it be worth a quick 10-minute conversation?" in email["body"]
    assert "Would you be open to one brief idea?" in linkedin["body"]
    combined = f"{email['body']} {linkedin['body']}".casefold()
    assert all(word not in combined for word in INTERNAL_WORDS)


def test_dry_run_does_not_insert_or_touch_sending_tables():
    client = FakeClient()
    add_previous(client, step=1, channel="email", status="approved")

    generate_followup_drafts_for_review_leads(
        client,
        followup_step=2,
        create_linkedin=False,
        dry_run=True,
    )

    assert client.inserts == {}
    assert "email_delivery_attempts" not in client.touched_tables
    assert "outreach_messages" not in client.touched_tables
    assert "lead_outreach" not in client.touched_tables
