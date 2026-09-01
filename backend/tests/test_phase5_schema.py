from pathlib import Path


def test_phase5_migration_enables_rls_for_every_business_table() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260901120000_phase5_core_schema.sql").read_text()
    tables = ("profiles", "icp_versions", "imports", "leads", "evidence", "lead_scores", "processing_jobs", "outreach_drafts", "audit_log")
    for table in tables:
        assert f"alter table public.{table} enable row level security" in migration


def test_privileged_functions_are_not_executable_by_public() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260901120000_phase5_core_schema.sql").read_text()
    assert "revoke all on function public.set_user_role" in migration
    assert "revoke all on function public.publish_icp_version" in migration


def test_hardening_removes_anonymous_function_access() -> None:
    hardening = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260901123500_phase5_security_hardening.sql").read_text()
    assert "public.publish_icp_version(uuid) from public, anon" in hardening
    assert "public.set_user_role(uuid, public.app_role) from public, anon" in hardening


def test_phase6_intake_is_atomic_and_queues_every_accepted_lead() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260901133000_phase6_lead_intake.sql").read_text()
    assert "create or replace function public.ingest_leads" in migration
    assert "on conflict (lower(linkedin_url))" in migration
    assert "insert into public.processing_jobs" in migration
    assert "revoke all on function public.ingest_leads" in migration
