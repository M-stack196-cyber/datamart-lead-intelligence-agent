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


def test_phase7_lead_management_uses_audited_role_controlled_functions() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260901140000_phase7_lead_management.sql").read_text()
    assert "revoke insert, update, delete on table public.leads from authenticated" in migration
    assert "create or replace function public.update_lead" in migration
    assert "create or replace function public.assign_lead" in migration
    assert "create or replace function public.delete_lead" in migration
    assert "'lead_deleted'" in migration
    assert "Admin role required" in migration


def test_phase7_locks_direct_lead_table_privileges_to_select() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260901140500_phase7_leads_privilege_lockdown.sql").read_text()
    assert "revoke all privileges on table public.leads from authenticated" in migration
    assert "grant select on table public.leads to authenticated" in migration


def test_phase8_claims_enrichment_jobs_without_exposing_worker_rpc() -> None:
    migration = (Path(__file__).parents[2] / "supabase" / "migrations" / "20260902120000_phase8_vibe_processing.sql").read_text()
    assert "create or replace function public.claim_next_enrichment_job" in migration
    assert "for update skip locked" in migration
    assert "revoke all on function public.claim_next_enrichment_job(text) from public, anon, authenticated" in migration
    assert "grant execute on function public.claim_next_enrichment_job(text) to service_role" in migration
