from __future__ import annotations

import argparse
from pathlib import Path

from app.lead_sources.apollo_csv_provider import ApolloCsvLeadSourceProvider
from app.services.lead_source_ingestion import prepare_and_score_leads


PERSISTENCE_NOT_IMPLEMENTED = (
    "Database persistence for generic CSV imports is not implemented yet. Use --dry-run."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import and score an Apollo CSV export.")
    parser.add_argument("--file", required=True, help="Path to the Apollo CSV export")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score leads without writing to the database",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dry_run:
        print(PERSISTENCE_NOT_IMPLEMENTED)
        return 1

    provider = ApolloCsvLeadSourceProvider(Path(args.file))
    result = prepare_and_score_leads(provider.fetch_leads())

    print(f"requested_count: {result.requested_count}")
    print(f"prepared_count: {result.prepared_count}")
    print(f"duplicate_count: {result.duplicate_count}")
    print(f"qualified_count: {result.qualified_count}")
    print(f"review_count: {result.review_count}")
    print(f"rejected_count: {result.rejected_count}")
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
