from types import SimpleNamespace

from scripts import generate_primary_drafts


def result(**overrides):
    values = {
        "source": "apollo_csv",
        "requested_limit": 25,
        "eligible_leads": 22,
        "skipped_existing": 0,
        "email_drafts_created": 22,
        "linkedin_drafts_created": 22,
        "errors": [],
        "previews": [
            SimpleNamespace(
                lead_id="lead-1",
                channel="email",
                subject="Quick question about Metric AI",
                body="Hi Maya, prospect-facing draft",
            )
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_generate_primary_drafts_dry_run_does_not_insert(monkeypatch, capsys):
    calls = {}
    monkeypatch.setattr(generate_primary_drafts, "service_role_client", lambda: "client")

    def fake_generate(client, **kwargs):
        calls["client"] = client
        calls.update(kwargs)
        return result(email_drafts_created=22, linkedin_drafts_created=22)

    monkeypatch.setattr(
        generate_primary_drafts,
        "generate_primary_drafts_for_review_leads",
        fake_generate,
    )

    assert generate_primary_drafts.main(
        ["--source", "apollo_csv", "--limit", "25", "--dry-run"]
    ) == 0

    assert calls["client"] == "client"
    assert calls["source"] == "apollo_csv"
    assert calls["limit"] == 25
    assert calls["dry_run"] is True
    assert calls["create_email"] is True
    assert calls["create_linkedin"] is True
    output = capsys.readouterr().out
    assert "eligible_leads: 22" in output
    assert "email_drafts_created: 22" in output
    assert "linkedin_drafts_created: 22" in output


def test_generate_primary_drafts_non_dry_run_calls_service(monkeypatch):
    calls = {}
    monkeypatch.setattr(generate_primary_drafts, "service_role_client", lambda: "client")

    def fake_generate(client, **kwargs):
        calls["client"] = client
        calls.update(kwargs)
        return result(email_drafts_created=1, linkedin_drafts_created=1)

    monkeypatch.setattr(
        generate_primary_drafts,
        "generate_primary_drafts_for_review_leads",
        fake_generate,
    )

    assert generate_primary_drafts.main(["--source", "apollo_csv", "--limit", "1"]) == 0
    assert calls["dry_run"] is False
    assert calls["client"] == "client"
