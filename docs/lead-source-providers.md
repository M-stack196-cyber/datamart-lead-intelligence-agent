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

## Seamless Placeholder

Seamless, Apollo enrichment, and other future sources should implement `LeadSourceProvider` and return `NormalizedLead` rows. Provider-specific API response quirks should stay inside each adapter so scoring, dedupe, and human-approved outreach can remain source-agnostic.

## Local Testing

Apollo tests use mocked HTTP responses and do not require API credits:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest tests/test_apollo_provider.py tests/test_apollo_lead_scoring.py -q
PYTHONPATH=. pytest tests -k "apollo or vibe" -q
PYTHONPATH=. pytest tests -k "vibe" -q
```

No lead-source provider may auto-send email or LinkedIn messages. Outreach remains generated as drafts and requires human approval for primary messages and follow-ups.
