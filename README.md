# Datamart Lead Intelligence Agent

Phase 1 establishes a production-oriented monorepo foundation for a Next.js dashboard and FastAPI service. Product workflows, authentication, database schema, and integrations are intentionally deferred.

## Repository layout

```text
.
├── frontend/              Next.js App Router application
├── backend/               FastAPI application and tests
├── supabase/migrations/   Reserved for approved future migrations
└── docs/                  Architecture and phase documentation
```

## Prerequisites (Ubuntu)

- Node.js 20.9 or newer and npm 10 or newer
- Python 3.12 or newer, including the `venv` module
- Git

On Ubuntu, install the system-provided Python tools with:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

Install a current Node.js LTS release using your preferred version manager, then verify `node --version` and `npm --version` satisfy the versions above.

## First-time setup

From the repository root:

```bash
npm install
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cp .env.example .env
cp backend/.env.example backend/.env
```

The example environment files contain local placeholders only. Keep real configuration in ignored `.env` files.

## Run locally

Start the frontend:

```bash
npm run dev:frontend
```

In a second terminal, start the API:

```bash
backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend
```

Open `http://localhost:3000` for the dashboard. The API health check is available at `http://localhost:8000/health`.

## Quality checks

Run every checkpoint validation from the repository root:

```bash
npm run check
```

Or run checks individually:

```bash
npm run lint
npm run build:frontend
npm run test:backend
```

## Phase 1 scope

This checkpoint includes the responsive dashboard shell, later-phase placeholders, backend structure, environment-driven CORS, and health-check coverage. It includes no Supabase migrations, authentication flows, dynamic roles/settings, business automation, or fabricated analytics.
