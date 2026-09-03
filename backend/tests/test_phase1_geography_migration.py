from pathlib import Path


def test_geography_migration_preserves_v1_and_publishes_v2_review_rule() -> None:
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260903080154_correct_icp_geography_rule.sql"
    ).read_text()

    assert "Opportunistic / Manual Review" in migration
    assert "rule ->> 'key' <> 'outside_geography'" in migration
    assert "'manual_review_rules'" in migration
    assert "set status = 'archived'" in migration
    assert "'datamart-icp-v2'" in migration
    assert "'Strong Fit', 'Good Fit', 'Opportunistic / Manual Review'" in migration
    assert "public.current_app_role() <> 'admin'" in migration
    assert "jsonb_array_length(latest_score.hard_stops)" in migration
