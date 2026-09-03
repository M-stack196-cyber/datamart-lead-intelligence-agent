# Approved System Architecture

The application is a deployment-neutral monorepo with three runtime processes:

1. Next.js dashboard in `frontend/`.
2. FastAPI service in `backend/`.
3. Durable lead-processing worker launched from `backend/app/workers/runner.py`.

## Provider boundaries

- Vibe Prospecting supplies company/contact discovery, enrichment, and business events.
- Public company sites, job pages, and news strengthen evidence with direct links.
- Deterministic rules apply hard exclusions and weighted ICP scoring.
- AWS Bedrock analyzes collected evidence and drafts outreach after scoring.
- Supabase provides PostgreSQL, Auth, role enforcement, and audit-ready persistence.

External providers live behind adapters so their payloads never leak into domain models.

## Processing sequence

`ingest -> deduplicate -> enqueue -> enrich -> verify evidence -> score -> analyze -> review/export`

Jobs will be stored in PostgreSQL and claimed by a separate worker. In-memory background tasks
must not be used for durable lead processing.

## Security boundary

Only the backend may read Vibe, Bedrock, Supabase service-role, or database secrets. The browser
may receive only Supabase public configuration. Row-Level Security and backend authorization must
both enforce admin, manager, and sales access.

## Current checkpoint

Phase 9 adds production hardening and deployment readiness. The verified codebase includes versioned ICP
scoring, intake validation, Vibe adapter boundaries, live capture and worker processing, intent-based
scoring, approval review, and sales handoff controls. The app keeps future areas as honest inactive
placeholders, including team/settings surfaces, until they are explicitly approved for implementation.

The project still enforces backend-only secrets, strict role checks, and deterministic qualification logic.
Provider adapters may enrich leads and evidence, but AI is never allowed to silently override hard
exclusion or approval rules.

## Access matrix

| Capability | Admin | Manager | Sales |
| --- | --- | --- | --- |
| View all leads and imports | Yes | Yes | No |
| View assigned/created leads | Yes | Yes | Yes |
| Create ICP draft | Yes | Yes | No |
| Publish ICP version | Yes | No | No |
| Change team roles / view audit log | Yes | No | No |

Supabase RLS is the primary data boundary. FastAPI independently validates bearer tokens and loads the
server-trusted role before serving protected endpoints. The service-role credential remains backend-only.

## ICP lifecycle and scoring

- ICP definitions are immutable versions behind `IcpRepository`. Supabase can replace the current
  file-backed repository without changing scoring callers.
- An Admin creates a draft from the active version. Publishing archives the previous active version;
  historical scores continue to reference the rule version that produced them.
- Lead qualification is deterministic. Bedrock may explain or draft from a score but cannot silently
  change rule outcomes.
- Unknown evidence remains unknown and receives no points. It is never treated as a match.
- Future rescoring creates a new result instead of overwriting historical qualification evidence.

## Lead intake boundary

`ingest_leads` is the Phase 6 transaction boundary. It accepts no more than 100 rows, validates a
researchable identity, enforces LinkedIn profile URL shape, deduplicates on normalized profile URL,
records the import outcome, and creates one queued `enrich` job for each accepted lead. The queue is
data only in this phase; provider execution remains disabled.

CSV parsing happens in the browser for preview, but the database repeats authoritative validation.
The security-definer RPC is intentionally executable only by authenticated users and derives the actor
from `auth.uid()`. It never accepts a caller-supplied owner or role.
