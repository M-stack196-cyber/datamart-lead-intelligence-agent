"""Idempotently seed the approved Phase 4 ICP as the first active Supabase version."""

from pathlib import Path
import json

from supabase import create_client

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    definition_path = Path(__file__).parents[1] / "data" / "icp_versions" / "datamart-v1.json"
    definition = json.loads(definition_path.read_text(encoding="utf-8"))
    row = {
        "external_id": definition["id"],
        "name": definition["name"],
        "version": definition["version"],
        "status": definition["status"],
        "definition": definition,
        "source": definition["source"],
        "effective_date": definition["effective_date"],
    }
    create_client(settings.supabase_url, settings.supabase_service_role_key).table("icp_versions").upsert(
        row, on_conflict="external_id"
    ).execute()
    print(f"Seeded {definition['id']} without changing user roles or lead data.")


if __name__ == "__main__":
    main()
