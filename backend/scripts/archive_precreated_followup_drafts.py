from __future__ import annotations

import argparse

from app.services.lead_source_persistence import service_role_client
from app.services.next_followup_drafts import archive_precreated_followup_drafts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive pre-created generic follow-up drafts that should wait for prior send/review."
    )
    parser.add_argument("--source", default="apollo_csv")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = archive_precreated_followup_drafts(
        service_role_client(),
        source=args.source,
        dry_run=not args.execute,
    )

    print(f"source: {result.source}")
    print(f"dry_run: {result.dry_run}")
    print(f"scanned: {result.scanned}")
    print(f"updated: {result.updated}")
    print(f"counts: {result.counts}")
    print(f"draft_ids: {result.draft_ids}")
    print(f"errors: {result.errors}")
    if result.dry_run:
        print("No rows were updated. Re-run with --execute to archive eligible drafts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
