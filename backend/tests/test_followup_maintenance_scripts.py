from types import SimpleNamespace

from scripts import archive_precreated_followup_drafts, refresh_primary_drafts


def test_archive_script_defaults_to_dry_run(monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(archive_precreated_followup_drafts, "service_role_client", lambda: "client")

    def fake_service(client, *, source, dry_run):
        calls["client"] = client
        calls["source"] = source
        calls["dry_run"] = dry_run
        return SimpleNamespace(
            source=source,
            dry_run=dry_run,
            scanned=2,
            updated=0,
            counts={"step_2_email": 2},
            draft_ids=["draft-1", "draft-2"],
            errors=[],
        )

    monkeypatch.setattr(
        archive_precreated_followup_drafts,
        "archive_precreated_followup_drafts",
        fake_service,
    )

    assert archive_precreated_followup_drafts.main(["--source", "apollo_csv"]) == 0

    assert calls == {"client": "client", "source": "apollo_csv", "dry_run": True}
    assert "dry_run: True" in capsys.readouterr().out


def test_archive_script_execute_updates(monkeypatch):
    calls = {}
    monkeypatch.setattr(archive_precreated_followup_drafts, "service_role_client", lambda: "client")

    def fake_service(client, *, source, dry_run):
        calls["dry_run"] = dry_run
        return SimpleNamespace(
            source=source,
            dry_run=dry_run,
            scanned=1,
            updated=1,
            counts={},
            draft_ids=[],
            errors=[],
        )

    monkeypatch.setattr(
        archive_precreated_followup_drafts,
        "archive_precreated_followup_drafts",
        fake_service,
    )

    assert archive_precreated_followup_drafts.main(["--execute"]) == 0
    assert calls["dry_run"] is False


def test_refresh_script_defaults_to_dry_run(monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(refresh_primary_drafts, "service_role_client", lambda: "client")

    def fake_service(client, *, source, dry_run):
        calls["client"] = client
        calls["source"] = source
        calls["dry_run"] = dry_run
        return SimpleNamespace(
            source=source,
            dry_run=dry_run,
            scanned=1,
            updated=0,
            counts={"email": 1},
            draft_ids=["draft-1"],
            errors=[],
        )

    monkeypatch.setattr(refresh_primary_drafts, "refresh_bad_primary_drafts", fake_service)

    assert refresh_primary_drafts.main(["--source", "apollo_csv"]) == 0

    assert calls == {"client": "client", "source": "apollo_csv", "dry_run": True}
    assert "dry_run: True" in capsys.readouterr().out
