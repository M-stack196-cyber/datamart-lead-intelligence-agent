from types import SimpleNamespace

from app.services.next_followup_drafts import (
    archive_precreated_followup_drafts,
    create_next_followup_draft,
    mark_draft_manually_sent,
    refresh_bad_primary_drafts,
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
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def order(self, *args, **kwargs):
        return self

    def execute(self):
        rows = self.client.rows.setdefault(self.table_name, [])
        if self.operation == "insert":
            payload = {"id": f"{self.table_name}-{len(rows) + 1}", **self.payload}
            rows.append(payload)
            self.client.inserts.setdefault(self.table_name, []).append(payload)
            return SimpleNamespace(data=[payload])

        filtered = rows
        for key, value in self.filters:
            filtered = [row for row in filtered if row.get(key) == value]

        if self.operation == "update":
            for row in filtered:
                row.update(self.payload)
            self.client.updates.setdefault(self.table_name, []).append(self.payload)
            return SimpleNamespace(data=filtered)

        return SimpleNamespace(data=filtered[: getattr(self, "limit_value", len(filtered))])


class FakeClient:
    def __init__(self):
        self.inserts = {}
        self.updates = {}
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
                }
            ],
            "lead_scores": [
                {
                    "lead_id": "lead-review",
                    "score": 80,
                    "review_reasons": ["Strong decision-maker fit"],
                    "scored_at": "2026-09-11T01:00:00Z",
                }
            ],
            "outreach_drafts": [],
            "email_delivery_attempts": [],
            "inbound_reply_events": [],
            "audit_log": [],
        }

    def table(self, name):
        return FakeQuery(self, name)


def add_draft(client, *, step, channel="email", status="draft", body="Hi Maya"):
    row = {
        "id": f"{channel}-{step}",
        "lead_id": "lead-review",
        "sequence_step": step,
        "channel": channel,
        "subject": "Subject" if channel == "email" else None,
        "body": body,
        "status": status,
        "evidence_ids": [],
        "review_notes": None,
    }
    client.rows["outreach_drafts"].append(row)
    return row


def test_next_followup_blocks_step_two_when_primary_is_still_draft():
    client = FakeClient()
    add_draft(client, step=1, status="draft")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    email = result.results["email"]
    assert email.created is False
    assert email.reason == "previous_step_not_sent_or_approved"
    assert client.inserts.get("outreach_drafts") is None


def test_next_followup_creates_step_two_after_previous_is_approved():
    client = FakeClient()
    add_draft(client, step=1, status="approved")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    email = result.results["email"]
    assert email.created is True
    assert email.sequence_step == 2
    assert client.inserts["outreach_drafts"][0]["status"] == "draft"
    assert client.inserts["outreach_drafts"][0]["sequence_step"] == 2


def test_next_followup_creates_step_two_after_previous_is_manual_sent():
    client = FakeClient()
    add_draft(client, step=1, status="manual_sent")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    email = result.results["email"]
    assert email.created is True
    assert email.sequence_step == 2


def test_next_followup_creates_step_two_after_previous_is_system_sent():
    client = FakeClient()
    add_draft(client, step=1, status="system_sent")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    email = result.results["email"]
    assert email.created is True
    assert email.sequence_step == 2


def test_system_sent_attempt_allows_next_followup_even_if_draft_status_is_draft():
    client = FakeClient()
    draft = add_draft(client, step=1, status="draft")
    client.rows["email_delivery_attempts"].append(
        {
            "id": "attempt-1",
            "lead_id": "lead-review",
            "outreach_draft_id": draft["id"],
            "status": "sent",
        }
    )

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is True
    assert result.results["email"].sequence_step == 2


def test_existing_next_step_is_returned_without_duplicate_insert():
    client = FakeClient()
    add_draft(client, step=1, status="approved")
    existing = add_draft(client, step=2, status="draft")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is False
    assert result.results["email"].reason == "existing_draft"
    assert result.results["email"].draft == existing
    assert client.inserts.get("outreach_drafts") is None


def test_terminal_next_step_is_reactivated_after_manual_send():
    for status in ("rejected", "archived", "cancelled"):
        client = FakeClient()
        add_draft(client, step=1, status="manual_sent")
        terminal = add_draft(client, step=2, status=status)

        result = create_next_followup_draft(
            client,
            lead_id="lead-review",
            actor_id="user-1",
            channel="email",
        )

        assert result.results["email"].created is True
        assert result.results["email"].reason == "reactivated_existing_terminal_draft"
        assert result.results["email"].sequence_step == 2
        assert terminal["status"] == "draft"
        assert terminal["reviewed_by"] is None
        assert terminal["reviewed_at"] is None
        assert terminal["review_notes"] == (
            "Reactivated as next follow-up draft by team after previous step was sent-like."
        )
        assert client.inserts.get("outreach_drafts") is None


def test_terminal_next_step_with_empty_body_is_reactivated_with_regenerated_copy():
    client = FakeClient()
    add_draft(client, step=1, status="manual_sent")
    terminal = add_draft(client, step=2, status="rejected", body="")
    terminal["subject"] = ""

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].reason == "reactivated_existing_terminal_draft"
    assert terminal["status"] == "draft"
    assert terminal["subject"]
    assert terminal["body"]
    assert "Would it be worth a quick 10-minute conversation?" in terminal["body"]


def test_needs_edit_primary_does_not_allow_followup():
    client = FakeClient()
    add_draft(client, step=1, status="needs_edit")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is False
    assert result.results["email"].reason == "previous_step_not_sent_or_approved"
    assert client.inserts.get("outreach_drafts") is None


def test_lead_reply_blocks_followup_creation():
    client = FakeClient()
    add_draft(client, step=1, status="approved")
    client.rows["inbound_reply_events"].append({"id": "reply-1", "lead_id": "lead-review"})

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is False
    assert result.results["email"].reason == "lead_replied"
    assert client.inserts.get("outreach_drafts") is None


def test_lead_reply_blocks_followup_even_when_primary_is_manual_sent():
    client = FakeClient()
    add_draft(client, step=1, status="manual_sent")
    client.rows["inbound_reply_events"].append({"id": "reply-1", "lead_id": "lead-review"})

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is False
    assert result.results["email"].reason == "lead_replied"
    assert client.inserts.get("outreach_drafts") is None


def test_sequence_stops_after_step_four():
    client = FakeClient()
    add_draft(client, step=4, status="approved")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is False
    assert result.results["email"].reason == "sequence_complete"


def test_channels_are_advanced_separately():
    client = FakeClient()
    add_draft(client, step=1, channel="email", status="approved")
    add_draft(client, step=1, channel="linkedin", status="draft")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="both",
    )

    assert result.results["email"].created is True
    assert result.results["email"].sequence_step == 2
    assert result.results["linkedin"].created is False
    assert result.results["linkedin"].reason == "previous_step_not_sent_or_approved"
    assert len(client.inserts["outreach_drafts"]) == 1


def test_manual_send_marks_draft_as_manual_sent_without_provider_send():
    client = FakeClient()
    draft = add_draft(client, step=1, status="draft")

    result = mark_draft_manually_sent(
        client,
        draft_id=draft["id"],
        actor_id="user-1",
        notes="Sent manually on LinkedIn",
    )

    assert result["status"] == "manual_sent"
    assert result["reviewed_by"] == "user-1"
    assert result["review_notes"] == "Sent manually on LinkedIn"
    assert client.rows["email_delivery_attempts"] == []
    assert client.inserts.get("outreach_drafts") is None


def test_archived_previous_step_does_not_advance_followup():
    client = FakeClient()
    add_draft(client, step=1, status="archived")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is False
    assert result.results["email"].reason == "previous_step_not_sent_or_approved"


def test_cancelled_previous_step_does_not_advance_followup():
    client = FakeClient()
    add_draft(client, step=1, status="cancelled")

    result = create_next_followup_draft(
        client,
        lead_id="lead-review",
        actor_id="user-1",
        channel="email",
    )

    assert result.results["email"].created is False
    assert result.results["email"].reason == "previous_step_not_sent_or_approved"


def test_archive_precreated_followups_dry_run_does_not_update_data():
    client = FakeClient()
    add_draft(client, step=1, status="draft")
    step_two = add_draft(client, step=2, status="draft")

    result = archive_precreated_followup_drafts(client, dry_run=True)

    assert result.scanned == 1
    assert result.updated == 0
    assert result.draft_ids == [step_two["id"]]
    assert step_two["status"] == "draft"
    assert client.updates == {}


def test_archive_precreated_followups_marks_archived_when_executed():
    client = FakeClient()
    add_draft(client, step=1, status="draft")
    step_two = add_draft(client, step=2, status="draft")

    result = archive_precreated_followup_drafts(client, dry_run=False)

    assert result.updated == 1
    assert step_two["status"] == "archived"


def test_refresh_bad_primary_drafts_updates_only_bad_draft_copy():
    client = FakeClient()
    bad = add_draft(
        client,
        step=1,
        channel="email",
        status="draft",
        body="I'm reaching out with a review-only note...",
    )
    approved = add_draft(
        client,
        step=1,
        channel="linkedin",
        status="approved",
        body="send a brief idea for review",
    )

    dry = refresh_bad_primary_drafts(client, dry_run=True)
    assert dry.scanned == 1
    assert bad["body"] == "I'm reaching out with a review-only note..."

    result = refresh_bad_primary_drafts(client, dry_run=False)

    assert result.updated == 1
    assert "review-only note" not in bad["body"].casefold()
    assert approved["body"] == "send a brief idea for review"
