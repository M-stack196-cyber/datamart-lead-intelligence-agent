"""Idempotently seed every repository ICP version in chronological order."""

from pathlib import Path
import json

from supabase import create_client

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    definition_paths = sorted(
        (Path(__file__).parents[1] / "data" / "icp_versions").glob("datamart-v*.json")
    )
    definitions = [json.loads(path.read_text(encoding="utf-8")) for path in definition_paths]
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    # Archive existing versions first so the database's one-active-version constraint
    # remains valid while the current active definition is upserted last.
    for definition in sorted(definitions, key=lambda item: item["status"] == "active"):
        row = {
            "external_id": definition["id"],
            "name": definition["name"],
            "version": definition["version"],
            "status": definition["status"],
            "definition": definition,
            "source": definition["source"],
            "effective_date": definition["effective_date"],
        }
        client.table("icp_versions").upsert(row, on_conflict="external_id").execute()

    print(f"Seeded {len(definitions)} ICP versions without changing user roles or lead data.")


if __name__ == "__main__":
    main()
