# Phase 1 Architecture

The project is a monorepo with two independently runnable applications:

- `frontend/` renders the Datamart workspace with Next.js App Router and Tailwind CSS.
- `backend/` exposes a FastAPI application. Phase 1 contains only operational health reporting.

The browser-facing application reads its API base URL from `NEXT_PUBLIC_API_URL`. The API permits configured browser origins from the comma-separated `CORS_ORIGINS` environment variable. Local defaults are safe for development and must be overridden by deployment configuration.

Supabase PostgreSQL and Supabase Auth are the approved data and identity services, but they are not connected in Phase 1. The migrations directory is retained with a placeholder file so the repository topology is ready without creating schema.

## Boundary

Navigation communicates planned information architecture only. Every future product area renders an explicit later-phase message and does not access data or provide operational behavior.
