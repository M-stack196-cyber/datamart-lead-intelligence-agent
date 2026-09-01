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

Phase 5 adds Supabase Auth, persistent business tables, RLS, audit records, server-validated API tokens,
and protected Next.js routes. Admin, manager, and sales permissions are resolved from `profiles`; role
values are never trusted from browser input or user-editable metadata. Provider adapters, research,
lead processing, and automatic outreach remain inactive.

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
