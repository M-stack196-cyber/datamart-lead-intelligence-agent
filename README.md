# Datamart Lead Intelligence Agent

An evidence-backed lead research and qualification workspace for Datamart. The approved system
uses Vibe Prospecting for B2B data, deterministic rules for ICP qualification, AWS Bedrock for
evidence-grounded analysis, and Supabase for PostgreSQL and authentication.

This checkpoint contains the Phase 5 data and identity foundation. It includes a Supabase schema,
authentication, role-aware access, protected dashboard routes, and versioned ICP controls. Live lead
research and provider calls remain intentionally inactive until their implementation phases are approved.

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

The worker command is reserved but intentionally exits until its workflow phase is approved:

```bash
npm run dev:worker
```

## Validate

```bash
npm run check
```

This runs frontend lint, a production frontend build, and backend tests.
