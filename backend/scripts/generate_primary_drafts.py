from __future__ import annotations

import argparse

from app.services.generic_outreach_drafts import generate_primary_drafts_for_review_leads
from app.services.lead_source_persistence import service_role_client


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate review-only primary outreach drafts for generic lead sources."
    )
    parser.add_argument("--source", default="apollo_csv")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-linkedin", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = service_role_client()
    result = generate_primary_drafts_for_review_leads(
        client,
        source=args.source,
        limit=args.limit,
        create_email=not args.no_email,
        create_linkedin=not args.no_linkedin,
        dry_run=args.dry_run,
    )

    print(f"source: {result.source}")
    print(f"requested_limit: {result.requested_limit}")
    print(f"eligible_leads: {result.eligible_leads}")
    print(f"skipped_existing: {result.skipped_existing}")
    print(f"email_drafts_created: {result.email_drafts_created}")
    print(f"linkedin_drafts_created: {result.linkedin_drafts_created}")
    print(f"errors: {result.errors}")
    print("preview_first_3_drafts:")
    for preview in result.previews:
        print(
            "- "
            f"lead_id={preview.lead_id} | "
            f"channel={preview.channel} | "
            f"subject={preview.subject or ''} | "
            f"body={preview.body[:240]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
