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

Evidence-grounded automatic outreach and follow-up sequencing remain deferred for generic CSV imports until generic evidence capture is added. The primary draft generator below creates review-only drafts from stored lead fields and ICP review context.

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

The generator considers only `status = review` leads for the requested `lead_source`, skips any lead/channel pair that already has a step-one draft, and creates at most one email draft and one LinkedIn draft per eligible lead. Follow-up draft sequencing remains a later phase and must stay approval-gated.

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
PYTHONPATH=. pytest tests -k "apollo or vibe" -q
PYTHONPATH=. pytest tests -k "vibe" -q
```

No lead-source provider may auto-send email or LinkedIn messages. Outreach remains generated as drafts and requires human approval for primary messages and follow-ups.
