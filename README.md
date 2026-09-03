# Datamart Lead Intelligence Agent

An evidence-backed lead research and qualification workspace for Datamart. The approved system
uses Vibe Prospecting for B2B data, deterministic rules for ICP qualification, AWS Bedrock for
evidence-grounded analysis, and Supabase for PostgreSQL and authentication.

This checkpoint contains the verified lead intelligence workflow through Phase 9. It includes versioned
ICP scoring, validated lead intake, Vibe enrichment boundaries, live capture and intent scoring,
decision fusion, review/approval flows, and the sales handoff/export gate. Sensitive runtime
configuration remains backend-only, and future sections such as team settings remain honest placeholders
until explicitly approved.

## Known phase status

1. Phase 0 — architecture foundation: complete
2. Phase 1 — ICP intelligence and versioning: complete
3. Phase 2 — lead intake and validation: complete
4. Phase 3 — Vibe provider boundary: complete
5. Phase 4 — live capture and queueing: complete
6. Phase 5 — intent scoring and evidence-based ranking: complete
7. Phase 6 — decision fusion and review readiness: complete
8. Phase 7 — approval review and outreach review: complete
9. Phase 8 — sales handoff and export controls: complete
10. Phase 9 — production hardening and deployment readiness: in progress / verified in code

## ICP intelligence

- The March 2026 Datamart playbook is structured as immutable ICP Version 1.
- Deterministic scoring records matched, failed, and unknown criteria.
- Hard-stop exclusions override positive fit signals.
- Results retain the exact ICP version and supporting evidence URLs.
- Draft, publish, and archive operations preserve historical versions.
- The dashboard shows active rules, personas, hard stops, and version status.

Managers and admins can create draft ICP versions. Only admins can publish a draft. Publishing archives
the previous active version while historical lead scores retain their original version reference.

## Repository layout

```text
frontend/                 Next.js dashboard
backend/app/api/          FastAPI routes
backend/app/integrations/ Vibe, Bedrock, and public-web adapters
backend/app/scoring/      Deterministic ICP scoring boundary
backend/data/icp_versions/ Structured, versioned ICP definitions
backend/app/workers/      Durable worker entry point
backend/tests/            Backend tests
supabase/migrations/      Versioned schema, role functions, and RLS policies
docs/                     Architecture documentation
```

## Prerequisites

- Node.js 20.9 or newer
- npm 10 or newer
- Python 3.12 or newer with `venv`

## Setup

```bash
npm install
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Keep real credentials in the ignored repository-root `.env`. Compare it with `.env.example` and
add missing variables without replacing existing secrets.

## Phase 5 Supabase setup

1. Create or select the Datamart Supabase project.
2. Apply `supabase/migrations/20260901120000_phase5_core_schema.sql` through the Supabase migration workflow.
3. Add the project URL and publishable/anon key to the frontend variables in the ignored `.env`.
4. Add the URL, anon key, service-role key, and database URL to the backend variables.
5. Run `npm run seed:icp` once to idempotently seed the approved active ICP.
6. Create the first Auth user, then bootstrap its `profiles.role` to `admin` from the SQL editor. Later role changes must use the `set_user_role` RPC.

Never place the service-role key or database URL in a `NEXT_PUBLIC_` variable. The migration enables RLS
for every business table and restricts ICP publishing and role changes to admins.

## Run locally

Frontend:

```bash
npm run dev:frontend
```

API:

```bash
npm run dev:backend
```

The dashboard runs at `http://localhost:3000`. API health is available at
`http://localhost:8000/health` and reports only whether integrations are configured, never values.

## Phase 8 controlled Vibe enrichment

- Accepted imports create queued `enrich` jobs. The worker claims one job at a time and stores only
  provider-returned lead fields and evidence links.
- It does not scrape LinkedIn and it never sends outreach messages.
- Add `VIBE_ENRICHMENT_URL` from your Vibe AgentSource account and set
  `VIBE_ENRICHMENT_ENABLED=true` only after reviewing Vibe's sample and credit estimate.
- Start with one job, then inspect Processing and Evidence before increasing the limit:

```bash
npm run dev:worker
# Optional after review: backend/.venv/bin/python -m app.workers.runner --limit 3
```

## Validate

```bash
npm run check
```

This runs frontend lint, a production frontend build, and backend tests.

## Phase 6 lead intake

- Paste up to 100 public LinkedIn profile URLs, one per line.
- Upload CSV files with `linkedin_url`, `company_name`, `person_name`, `title`, `company_url`, `email`, `country`, and `industry` columns.
- Every batch creates an immutable import summary with row-level rejection reasons.
- Duplicate LinkedIn URLs are rejected without duplicating lead records.
- Every accepted lead is queued for future enrichment; Phase 6 does not execute the queue.
- Sales users see leads they created or were assigned. Managers and admins can see all leads.

The intake RPC performs validation, insertion, deduplication, audit logging, and job creation in one
database transaction. It does not scrape LinkedIn or call Vibe, Bedrock, or public-web providers.
