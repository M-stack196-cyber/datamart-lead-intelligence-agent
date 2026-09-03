from pathlib import Path


def test_phase2_pipeline_rpc_is_idempotent_service_only_and_persists_intelligence() -> None:
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260903081001_complete_enrichment_intelligence_pipeline.sql"
    ).read_text()

    assert "unique (source_job_id)" in migration
    assert "if claimed_job.status = 'completed'" in migration
    assert "on conflict (source_job_id) do update" in migration
    assert "lower(source_url) = lower" in migration
    assert "insert into public.lead_scores" in migration
    assert "intent_score" in migration
    assert "review_reasons" in migration
    assert "computed_status := 'disqualified'" in migration
    assert "computed_status := 'review'" in migration
    assert "computed_status := 'nurture'" in migration
    assert ") from public, anon, authenticated" in migration
    assert ") to service_role" in migration


def test_phase2_pipeline_never_erases_stored_values_with_blank_provider_fields() -> None:
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260903081001_complete_enrichment_intelligence_pipeline.sql"
    ).read_text()

    assert "coalesce(nullif(trim(provider_fields ->> 'company_name'), ''), company_name)" in migration
    assert "coalesce(nullif(trim(provider_fields ->> 'person_name'), ''), person_name)" in migration
