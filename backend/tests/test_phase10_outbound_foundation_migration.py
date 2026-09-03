from pathlib import Path


def migration_text() -> str:
    return (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260903110000_outbound_execution_foundation.sql"
    ).read_text()


def test_outbound_foundation_creates_sequence_message_event_suppression_and_crm_tables() -> None:
    migration = migration_text()

    for table in (
        "outreach_sequences",
        "outreach_sequence_steps",
        "lead_outreach",
        "outreach_messages",
        "outreach_events",
        "suppression_entries",
        "crm_sync_state",
    ):
        assert f"create table public.{table}" in migration
        assert f"alter table public.{table} enable row level security" in migration

    assert "create type public.outbound_lifecycle_status" in migration
    assert "create type public.outbound_direction" in migration
    assert "create type public.crm_sync_status" in migration
    assert "create type public.suppression_kind" in migration
    assert "unique (sequence_id, step_number)" in migration
    assert "unique (lead_id, sequence_id)" in migration
    assert "unique (normalized_email)" in migration
    assert "unique (lead_id, provider_key)" in migration
    assert "idempotency_key text not null unique" in migration
    assert "create or replace function public.is_email_suppressed" in migration


def test_outbound_foundation_installs_role_aware_policies() -> None:
    migration = migration_text()

    assert "sequences_select" in migration
    assert "sequence_steps_select" in migration
    assert "lead_outreach_select" in migration
    assert "outreach_messages_select" in migration
    assert "outreach_events_select" in migration
    assert "suppression_entries_select" in migration
    assert "crm_sync_state_select" in migration
    assert "public.is_manager_or_admin()" in migration
    assert "public.can_access_lead(lead_id)" in migration


def test_outbound_foundation_seeds_the_mvp_email_sequence() -> None:
    migration = migration_text()

    assert "datamart-outbound-sequence-v1" in migration
    assert "Datamart Outreach Sequence" in migration
    assert "A brief question about {{company_name}}" in migration
    assert "Following up on {{company_name}}" in migration
    assert "One more follow-up for {{company_name}}" in migration
    assert "Closing the loop on {{company_name}}" in migration
