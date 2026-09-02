from pathlib import Path


def test_phase7_assign_lead_rejects_disqualified_records() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260901140000_phase7_lead_management.sql").read_text()
    assert "create or replace function public.assign_lead" in migration
    assert "status <> 'disqualified'" in migration
    assert "Lead must be approved for sales and cannot be disqualified" in migration
