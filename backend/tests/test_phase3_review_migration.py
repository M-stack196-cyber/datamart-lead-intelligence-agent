from pathlib import Path


def migration_text() -> str:
    return (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260903081632_role_enforced_lead_review_workflow.sql"
    ).read_text()


def test_sales_visibility_requires_assignment_and_sales_approval() -> None:
    migration = migration_text()

    assert "assigned_to = auth.uid()" in migration
    assert "sales_approved_at is not null" in migration
    assert "status <> 'disqualified'" in migration
    assert "or created_by = auth.uid()" not in migration


def test_review_outcomes_are_admin_only_reasoned_and_audited() -> None:
    migration = migration_text()

    assert "create or replace function public.set_lead_review_outcome" in migration
    assert "public.current_app_role() <> 'admin'" in migration
    assert "A review reason is required" in migration
    assert "outcome not in ('disqualified', 'nurture')" in migration
    assert "'lead_disqualified'" in migration
    assert "'lead_moved_to_nurture'" in migration
    assert "insert into public.audit_log" in migration
    assert "from public, anon" in migration


def test_generic_lead_edit_cannot_bypass_review_or_sales_visibility() -> None:
    migration = migration_text()

    assert "Lead status changes require the audited review workflow" in migration
    assert "Sales can edit only assigned, approved leads" in migration
    assert "existing_lead.sales_approved_at is not null" in migration


def test_lead_and_review_screens_show_saved_intelligence_and_role_actions() -> None:
    root = Path(__file__).parents[2] / "frontend" / "src" / "components"
    leads = (root / "leads-workspace.tsx").read_text()
    review = (root / "review-workspace.tsx").read_text()

    for field in ("disposition", "intent_level", "hard_stops", "review_reasons"):
        assert field in leads
    assert "sales_approved_at" in leads
    assert "evidence(count)" in leads
    for field in ("publisher", "excerpt", "supports_fields", "evaluations", "intent_reasons"):
        assert field in review
    assert 'role !== "admin"' in review
    assert "set_lead_review_outcome" in review
