# Datamart Lead Intelligence Agent

An evidence-backed lead research and qualification workspace for Datamart. The approved system
uses Vibe Prospecting for B2B data, deterministic rules for ICP qualification, AWS Bedrock for
evidence-grounded analysis, and Supabase for PostgreSQL and authentication.

This checkpoint contains the new architecture foundation only. It intentionally contains no live
lead workflow, database schema, authentication flow, scoring logic, or provider calls.

## Repository layout

```text
frontend/                 Next.js dashboard
backend/app/api/          FastAPI routes
backend/app/integrations/ Vibe, Bedrock, and public-web adapters
backend/app/scoring/      Deterministic ICP scoring boundary
backend/app/workers/      Durable worker entry point
backend/tests/            Backend tests
supabase/migrations/      Approved migrations (currently empty)
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
