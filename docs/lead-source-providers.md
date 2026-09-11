# Lead Source Providers

Datamart lead discovery now uses a small provider boundary:

- `NormalizedLead` captures common person, company, contact, provider identity, and raw-source fields.
- `LeadSourceProvider` exposes `fetch_leads(limit: int) -> list[NormalizedLead]`.
- `lead_source_ingestion.prepare_and_score_leads` deduplicates normalized leads and runs them through the existing Datamart ICP scoring pipeline.

## Vibe / AgentSource

Vibe remains the original provider and is not removed or replaced. Existing Vibe discovery, scoring, event enrichment, persistence, and tests are still provider-specific.

Current production status: Vibe `/prospects` calls are blocked by unavailable API credits / `403`, so it should not be the only daily capture path until credits are restored.

Required env vars:

- `VIBE_API_KEY`
- `VIBE_API_BASE_URL`
- `VIBE_ENRICHMENT_ENABLED`
- `DAILY_VIBE_LEAD_LIMIT`
- `VIBE_ALLOW_OVER_DAILY_CAP`

## Apollo

Apollo is provider 2. The Apollo adapter calls the People Search endpoint only when `APOLLO_API_KEY` is configured, maps returned people into `NormalizedLead`, preserves the full Apollo row in `raw_source_data`, and never sends outreach.

Required env vars:

- `APOLLO_API_KEY`
- `APOLLO_BASE_URL` defaults to `https://api.apollo.io`

Internal cron endpoint:

```text
GET /internal/lead-sources/apollo/discovery-cycle?limit=100
Authorization: Bearer $CRON_SECRET
```

The endpoint fetches, normalizes, deduplicates, and scores Apollo leads. It currently returns `prepared_count` instead of `stored_count` because the existing durable discovery persistence path is Vibe-specific.

## Apollo CSV Temporary Testing Provider

Apollo CSV import exists as a temporary testing source because Apollo free/trial access does not provide the API/export workflow needed for normal automated discovery. A manually saved Apollo CSV batch can be normalized into `NormalizedLead` rows and scored through the same Datamart ICP pipeline as the API providers.

Dry-run a local CSV:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/import_apollo_csv.py --file /path/to/apollo.csv --dry-run
```

Persist a local CSV into Supabase after reviewing the dry-run output:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/import_apollo_csv.py --file /path/to/apollo.csv
```

Required backend env vars for persistence:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Generic imports use the backend service-role client only. The service role key must stay in backend-only ignored environment files and must never be exposed to the frontend.

Generic persistence stores Apollo CSV rows in `leads`, writes the current ICP result to `lead_scores`, tracks `lead_source`, `source_id`, `source_captured_at`, and preserves the full Apollo row in `raw_source_data`. It deduplicates by email, LinkedIn URL, source plus source ID, and company URL plus person name. The current durable Vibe discovery RPC remains Vibe-specific and is not reused for CSV imports.

The CSV path is temporary. Production discovery should use an approved API provider such as Apollo paid, Clay, Seamless, Vibe, or a similar provider. CSV import does not send emails, LinkedIn messages, or Apollo sequences; outreach remains human-approved.

Evidence-grounded automatic outreach remains deferred for generic CSV imports until generic evidence capture is added. The draft generators below create review-only primary and follow-up drafts from stored lead fields and ICP review context.

## Generating Review-Only Primary Drafts

Apollo CSV and other generic lead-source imports can generate primary step-one outreach drafts for admin/sales review. Draft generation writes `draft` rows to `outreach_drafts` only; it does not send email, send LinkedIn messages, call Gmail delivery, or start provider-side sequences.

Preview the drafts first:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/generate_primary_drafts.py --source apollo_csv --limit 25 --dry-run
```

Create review-only primary drafts:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/generate_primary_drafts.py --source apollo_csv --limit 25
```

The generator considers only `status = review` leads for the requested `lead_source`, skips any lead/channel pair that already has a step-one draft, and creates at most one email draft and one LinkedIn draft per eligible lead. Follow-up draft sequencing uses the draft-only flow below and must stay approval-gated.

## Follow-Up Draft Sequence

Generic lead sources can also generate draft-only follow-ups after primary drafts exist. Follow-ups should be created one step at a time after the previous step has been reviewed/sent-like and only when no inbound reply has been recorded. Sequence steps map as:

- `sequence_step = 1`: primary draft
- `sequence_step = 2`: follow-up 1
- `sequence_step = 3`: follow-up 2
- `sequence_step = 4`: follow-up 3

The dashboard review workflow uses:

- `PATCH /outreach-drafts/{draft_id}/manual-send`
- `POST /leads/{lead_id}/outreach/next-followup-draft`

Manual-send records that a team member sent the draft outside the system. The current schema has no `sent` draft status, so it uses the existing approved/sent-like draft state plus review notes and audit metadata. The next-follow-up endpoint checks `inbound_reply_events` and returns `lead_replied` instead of creating a draft when a reply exists.

The older CLI follow-up generator is retained for maintenance and testing, but it now also requires the previous channel step to be approved/sent-like. It should not be used to pre-create all follow-ups at once.

Preview follow-up 1 for eligible leads only:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/generate_followup_drafts.py --source apollo_csv --limit 25 --step 2 --dry-run
```

Create follow-up 1 drafts:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/generate_followup_drafts.py --source apollo_csv --limit 25 --step 2
```

Preview later follow-ups:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/generate_followup_drafts.py --source apollo_csv --limit 25 --step 3 --dry-run
PYTHONPATH=. python scripts/generate_followup_drafts.py --source apollo_csv --limit 25 --step 4 --dry-run
```

Follow-ups are stored only as `draft` rows in `outreach_drafts`. No message is sent automatically, no Gmail or LinkedIn delivery is called, and admin/sales approval remains required before any send. The team can decide later whether email or LinkedIn is the right channel for each lead.

Safe maintenance scripts for existing test data:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python scripts/archive_precreated_followup_drafts.py --source apollo_csv
PYTHONPATH=. python scripts/archive_precreated_followup_drafts.py --source apollo_csv --execute
PYTHONPATH=. python scripts/refresh_primary_drafts.py --source apollo_csv
PYTHONPATH=. python scripts/refresh_primary_drafts.py --source apollo_csv --execute
```

Both scripts default to dry-run. The archive script does not delete rows; because the current `outreach_status` enum only supports `draft`, `approved`, and `rejected`, it archives unsafe pre-created follow-ups by setting eligible draft rows to `rejected`.

## Review Dashboard

The dashboard `/review` page loads generic lead-source review rows through the backend review workspace API, groups email and LinkedIn drafts by sequence step 1 through 4, and lets admins/managers mark draft status as approved, rejected, or needs edit. These review actions only update draft review fields; they do not send email, copy LinkedIn messages, call Gmail delivery, or call Apollo sequences.

API endpoints:

- `GET /leads/review-workspace?source=apollo_csv&status=review&limit=50&include_drafts=true`
- `PATCH /outreach-drafts/{draft_id}/review`

TODO: Extend the existing export workspace with a CSV that includes lead fields, score/review reasons, and each draft subject/body/status by channel and sequence step. Existing exports are unchanged for now.

## Seamless Placeholder

Seamless, Apollo enrichment, and other future sources should implement `LeadSourceProvider` and return `NormalizedLead` rows. Provider-specific API response quirks should stay inside each adapter so scoring, dedupe, and human-approved outreach can remain source-agnostic.

## Local Testing

Apollo tests use mocked HTTP responses and do not require API credits:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest tests/test_apollo_provider.py tests/test_apollo_lead_scoring.py -q
PYTHONPATH=. pytest tests/test_apollo_csv_provider.py tests/test_apollo_csv_import_scoring.py -q
PYTHONPATH=. pytest tests/test_lead_source_persistence.py tests/test_apollo_csv_import_persistence.py -q
PYTHONPATH=. pytest tests/test_generic_outreach_drafts.py tests/test_generate_primary_drafts_script.py -q
PYTHONPATH=. pytest tests/test_generic_followup_drafts.py tests/test_generate_followup_drafts_script.py -q
PYTHONPATH=. pytest tests -k "apollo or vibe" -q
PYTHONPATH=. pytest tests -k "vibe" -q
```

No lead-source provider may auto-send email or LinkedIn messages. Outreach remains generated as drafts and requires human approval for primary messages and follow-ups.
