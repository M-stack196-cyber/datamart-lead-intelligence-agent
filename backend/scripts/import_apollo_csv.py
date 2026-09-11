from __future__ import annotations

import argparse
from pathlib import Path

from app.lead_sources.apollo_csv_provider import ApolloCsvLeadSourceProvider
from app.services.lead_source_ingestion import prepare_and_score_leads
from app.services.lead_source_persistence import (
    persist_scored_leads,
    service_role_client,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import and score an Apollo CSV export.")
    parser.add_argument("--file", required=True, help="Path to the Apollo CSV export")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score leads without writing to the database",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    provider = ApolloCsvLeadSourceProvider(Path(args.file))
    result = prepare_and_score_leads(provider.fetch_leads())

    persistence = None
    if not args.dry_run:
        client = service_role_client()
        persistence = persist_scored_leads(
            client,
            result,
            file_name=Path(args.file).name,
        )

    print(f"requested_count: {result.requested_count}")
    print(f"prepared_count: {result.prepared_count}")
    if persistence:
        print(f"inserted_count: {persistence.inserted_count}")
        print(f"updated_count: {persistence.updated_count}")
        print(f"duplicate_count: {persistence.duplicate_count}")
    else:
        print("inserted_count: 0")
        print("updated_count: 0")
        print(f"duplicate_count: {result.duplicate_count}")
    print(f"qualified_count: {result.qualified_count}")
    print(f"review_count: {result.review_count}")
    print(f"rejected_count: {result.rejected_count}")
    print(f"errors: {(persistence.errors if persistence else result.errors)}")
    print(f"warnings: {(persistence.warnings if persistence else result.warnings)}")
    print("top_scored_leads:")

    top_scored = sorted(
        result.scored,
        key=lambda scored: scored.score.score,
        reverse=True,
    )[:10]
    for item in top_scored:
        prospect = item.prospect
        reasons = item.score.review_reasons or item.score.hard_stops
        reason_text = "; ".join(reasons) if reasons else "none"
        print(
            "- "
            f"person_name={prospect.get('person_name') or 'unknown'} | "
            f"title={prospect.get('title') or 'unknown'} | "
            f"company_name={prospect.get('company_name') or 'unknown'} | "
            f"score={item.score.score} | "
            f"status={item.pipeline_status} | "
            f"disposition={item.score.disposition} | "
            f"review_reasons={reason_text}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
