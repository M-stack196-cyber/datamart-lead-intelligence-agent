-- Minimal existing table contract for exercising the real ingest migration in
-- an isolated PostgreSQL database, without Supabase Auth or production data.
create table public.imports (
  id uuid primary key default gen_random_uuid(), file_name text, source text,
  status text, total_rows integer, created_by uuid, accepted_rows integer,
  rejected_rows integer, error_summary jsonb, completed_at timestamptz
);
create table public.leads (
  id uuid primary key default gen_random_uuid(), import_id uuid, created_by uuid,
  company_name text, person_name text, title text, linkedin_url text,
  company_url text, email text, country text, industry text,
  annual_revenue bigint, employee_count integer, business_model text,
  growth_stage text, buying_behavior text, status text, raw_source_data jsonb,
  vibe_prospect_id text, vibe_business_id text, lead_source text,
  source_captured_at timestamptz, created_at timestamptz default now(),
  updated_at timestamptz default now()
);
alter table public.leads enable row level security;
alter table public.imports enable row level security;
create table public.audit_log (
  id uuid primary key default gen_random_uuid(), actor_id uuid, action text,
  entity_type text, entity_id text, details jsonb
);
alter table public.audit_log enable row level security;
create unique index leads_vibe_business_id_unique on public.leads(lower(vibe_business_id));
create unique index leads_vibe_prospect_id_unique on public.leads(lower(vibe_prospect_id));
