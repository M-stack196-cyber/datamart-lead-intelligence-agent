from pathlib import Path


def migration_text() -> str:
    return (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260903082524_evidence_grounded_outreach_drafts.sql"
    ).read_text()


def test_draft_lifecycle_is_role_checked_evidence_bound_and_audited() -> None:
    migration = migration_text()

    assert "create_generated_outreach_draft" in migration
    assert "Every draft evidence item must belong to the lead" in migration
    assert "latest_score.disposition in ('Disqualified', 'Not Qualified')" in migration
    assert "create or replace function public.update_outreach_draft" in migration
    assert "where id = target_draft_id and status = 'draft'" in migration
    assert "Admin role required for outreach approval" in migration
    assert "reviewed_by = actor_id" in migration
    assert "review_notes = trim(notes)" in migration
    assert "insert into public.audit_log" in migration


def test_sales_can_select_only_approved_drafts_and_mutations_use_rpcs() -> None:
    migration = migration_text()

    assert "status = 'approved'" in migration
    assert "public.can_access_lead(lead_id)" in migration
    assert "revoke insert, update, delete on table public.outreach_drafts" in migration
    assert "from public, anon, authenticated" in migration
    assert "to service_role" in migration


def test_linkedin_ui_is_approved_copy_only() -> None:
    component = (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "components"
        / "outreach-draft-panel.tsx"
    ).read_text()

    assert 'draft.status !== "approved" || draft.channel !== "linkedin"' in component
    assert "navigator.clipboard.writeText" in component
    assert "Copy LinkedIn message" in component
    assert "LinkedIn remains copy-only and manual" in component
    assert "linkedin.com" not in component
