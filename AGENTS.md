# Datamart Lead Intelligence Agent — Contributor Guide

## Approved stack

- Monorepo with an npm-managed Next.js frontend and a Python FastAPI backend.
- Frontend: Next.js App Router, TypeScript, Tailwind CSS, and ESLint.
- Backend: FastAPI with its virtual environment at `backend/.venv`.
- Data and identity: Supabase PostgreSQL and Supabase Auth when their phase is approved.

Do not substitute frameworks, package managers, databases, or authentication providers without explicit project approval.

## Phase-by-phase workflow

1. Read the current phase requirements and identify its explicit boundaries.
2. Implement only behavior assigned to that phase. Keep later areas as neutral placeholders.
3. Add configuration through environment variables and commit examples only; never commit secrets.
4. Add or update tests for behavior introduced in the phase.
5. Run frontend lint, a production build, and backend tests before committing.
6. Review the complete diff and ignored files for generated output, dependencies, environments, and credentials.
7. Use a focused checkpoint commit after every approved phase.

## Current boundary: Phase 1

Phase 1 establishes structure, styling, local setup, an API health endpoint, and CORS configuration. It does not create Supabase tables or implement authentication, roles, settings behavior, AI, lead workflows, research, scoring, outreach, messaging, reply detection, or meetings. Future-phase navigation must remain non-functional placeholder content until explicitly approved.

## Quality expectations

- Prefer small, typed, testable units and clear names.
- Do not invent customer data, metrics, charts, or business results.
- Update `README.md` when setup or commands change.
- Keep `supabase/migrations/` empty of migrations until a database phase is approved.
