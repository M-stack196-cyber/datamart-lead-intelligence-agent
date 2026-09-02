from pathlib import Path


def test_phase9_requires_admin_approval_before_sales_assignment() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260902150000_phase9_sales_handoff.sql").read_text()
    assert "sales_approved_at" in migration
    assert "create or replace function public.approve_lead_for_sales" in migration
    assert "Admin role required" in migration
    assert "sales_approved_at is not null" in migration
    assert "status <> 'disqualified'" in migration
