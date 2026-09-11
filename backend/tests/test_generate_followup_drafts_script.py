from types import SimpleNamespace

from scripts import generate_followup_drafts


def result(**overrides):
    values = {
        "source": "apollo_csv",
        "requested_limit": 25,
        "followup_step": 2,
        "eligible_leads": 22,
        "skipped_missing_previous": 0,
        "skipped_existing": 0,
        "email_drafts_created": 22,
        "linkedin_drafts_created": 22,
        "errors": [],
        "previews": [
            SimpleNamespace(
                lead_id="lead-1",
                channel="email",
                subject="Following up on Metric AI",
                body="Hi Maya, following up.",
            )
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_generate_followup_drafts_dry_run_calls_service(monkeypatch, capsys):
    calls = {}
    monkeypatch.setattr(generate_followup_drafts, "service_role_client", lambda: "client")

    def fake_generate(client, **kwargs):
        calls["client"] = client
        calls.update(kwargs)
        return result()

    monkeypatch.setattr(
        generate_followup_drafts,
        "generate_followup_drafts_for_review_leads",
        fake_generate,
    )

    assert generate_followup_drafts.main(
        ["--source", "apollo_csv", "--limit", "25", "--step", "2", "--dry-run"]
    ) == 0

    assert calls["client"] == "client"
    assert calls["source"] == "apollo_csv"
    assert calls["limit"] == 25
    assert calls["followup_step"] == 2
    assert calls["dry_run"] is True
    assert calls["create_email"] is True
    assert calls["create_linkedin"] is True
    output = capsys.readouterr().out
    assert "followup_step: 2" in output
    assert "email_drafts_created: 22" in output
    assert "linkedin_drafts_created: 22" in output


def test_generate_followup_drafts_non_dry_run_calls_service(monkeypatch):
    calls = {}
    monkeypatch.setattr(generate_followup_drafts, "service_role_client", lambda: "client")

    def fake_generate(client, **kwargs):
        calls["client"] = client
        calls.update(kwargs)
        return result(email_drafts_created=1, linkedin_drafts_created=0)

    monkeypatch.setattr(
        generate_followup_drafts,
        "generate_followup_drafts_for_review_leads",
        fake_generate,
    )

    assert generate_followup_drafts.main(
        ["--source", "apollo_csv", "--limit", "1", "--step", "3", "--no-linkedin"]
    ) == 0
    assert calls["dry_run"] is False
    assert calls["followup_step"] == 3
    assert calls["create_email"] is True
    assert calls["create_linkedin"] is False
