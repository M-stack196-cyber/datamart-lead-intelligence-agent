from pathlib import Path


def migration_text() -> str:
    return (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260903083500_explicitly_approved_gmail_delivery.sql"
    ).read_text()


def test_gmail_delivery_requires_every_approval_gate_and_audits_outcomes() -> None:
    migration = migration_text()

    assert "approved_draft.status <> 'approved'" in migration
    assert "approved_draft.channel <> 'email'" in migration
    assert "target_lead.status = 'disqualified'" in migration
    assert "target_lead.sales_approved_at is null" in migration
    assert "target_lead.assigned_to is null" in migration
    assert "Sales user is not assigned to this lead" in migration
    assert "A valid lead email address is required" in migration
    assert "'email_send_attempted'" in migration
    assert "'email_send_succeeded'" in migration
    assert "'email_send_failed'" in migration


def test_delivery_table_has_rls_and_service_only_write_functions() -> None:
    migration = migration_text()

    assert "alter table public.email_delivery_attempts enable row level security" in migration
    assert "revoke all on table public.email_delivery_attempts from anon, authenticated" in migration
    assert "grant select on table public.email_delivery_attempts to authenticated" in migration
    assert "from public, anon, authenticated" in migration
    assert "to service_role" in migration


def test_workers_contain_no_email_sending_path() -> None:
    workers = Path(__file__).parents[1] / "app" / "workers"
    source = "\n".join(path.read_text() for path in workers.glob("*.py"))

    assert "GmailClient" not in source
    assert "send-email" not in source


def test_email_ui_has_disabled_state_and_second_confirmation_click() -> None:
    component = (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "components"
        / "outreach-draft-panel.tsx"
    ).read_text()

    assert "Gmail sending is disabled because credentials are not configured" in component
    assert 'draft.status !== "approved" || draft.channel !== "email"' in component
    assert "Final confirmation: send this exact approved draft" in component
    assert "Confirm send email" in component
    assert "{ confirm: true }" in component
