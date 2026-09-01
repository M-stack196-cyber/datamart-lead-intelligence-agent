# Datamart Lead Intelligence Agent - Contributor Guide

## Approved architecture

- Monorepo with an npm-managed Next.js frontend and Python FastAPI backend.
- Frontend: Next.js App Router, TypeScript, Tailwind CSS, and ESLint.
- Backend: FastAPI, Pydantic, SQLAlchemy, PostgreSQL, and a separate worker process.
- Data and identity: Supabase PostgreSQL, Supabase Auth, and Row-Level Security.
- Lead data: Vibe Prospecting behind a typed adapter.
- AI: AWS Bedrock behind a typed adapter.

Do not substitute providers or frameworks without explicit approval.

## Phase workflow

1. Implement only the explicitly approved phase.
2. Keep future areas as honest, inactive placeholders.
3. Store secrets only in ignored environment files.
4. Add or update tests for introduced behavior.
5. Run frontend lint/build and backend tests before a checkpoint.
6. Review the complete diff and ignored files before committing.
7. Use a focused checkpoint commit after every approved phase.

## Current boundary: architecture foundation

The foundation establishes topology, configuration contracts, navigation, API health reporting,
and empty provider/domain boundaries. It does not create Supabase tables, authentication flows,
roles, lead ingestion, Vibe calls, public research, scoring, Bedrock calls, outreach, or exports.

## Non-negotiable product rules

- Hard disqualifiers are deterministic and cannot be silently overridden by AI.
- Important conclusions must reference stored evidence and direct source links.
- Unknown information remains unknown; never fabricate estimates or business activity.
- Never scrape logged-in LinkedIn pages or send LinkedIn messages automatically.
- Never log, return, commit, or expose provider secrets.
