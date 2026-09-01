begin;

create extension if not exists pgcrypto;

create type public.app_role as enum ('admin', 'manager', 'sales');
create type public.icp_version_status as enum ('draft', 'active', 'archived');
create type public.lead_status as enum ('new', 'researching', 'scored', 'qualified', 'review', 'nurture', 'disqualified', 'archived');
create type public.processing_status as enum ('queued', 'running', 'completed', 'failed', 'cancelled');
create type public.import_status as enum ('pending', 'processing', 'completed', 'failed');
create type public.outreach_status as enum ('draft', 'approved', 'rejected');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  full_name text,
  avatar_url text,
  role public.app_role not null default 'sales',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.icp_versions (
  id uuid primary key default gen_random_uuid(),
  external_id text not null unique,
  name text not null,
  version integer not null check (version > 0),
  status public.icp_version_status not null default 'draft',
  definition jsonb not null,
  source text not null,
  effective_date date not null,
  created_by uuid references public.profiles(id),
  approved_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  published_at timestamptz,
  archived_at timestamptz,
  unique (name, version)
);

create unique index one_active_icp_version
  on public.icp_versions ((status)) where status = 'active';

create table public.imports (
  id uuid primary key default gen_random_uuid(),
  file_name text not null,
  source text not null check (source in ('csv', 'profile_links', 'vibe')),
  status public.import_status not null default 'pending',
  total_rows integer not null default 0 check (total_rows >= 0),
  accepted_rows integer not null default 0 check (accepted_rows >= 0),
  rejected_rows integer not null default 0 check (rejected_rows >= 0),
  error_summary jsonb not null default '{}'::jsonb,
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table public.leads (
  id uuid primary key default gen_random_uuid(),
  import_id uuid references public.imports(id) on delete set null,
  assigned_to uuid references public.profiles(id) on delete set null,
  created_by uuid not null references public.profiles(id),
  company_name text not null,
  person_name text,
  title text,
  linkedin_url text,
  company_url text,
  email text,
  country text,
  industry text,
  annual_revenue bigint check (annual_revenue >= 0),
  employee_count integer check (employee_count >= 0),
  business_model text,
  growth_stage text,
  buying_behavior text,
  status public.lead_status not null default 'new',
  raw_source_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index leads_linkedin_url_unique
  on public.leads (lower(linkedin_url)) where linkedin_url is not null;
create index leads_status_idx on public.leads(status);
create index leads_assigned_to_idx on public.leads(assigned_to);
create index leads_company_name_idx on public.leads(lower(company_name));

create table public.evidence (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  evidence_type text not null check (evidence_type in ('linkedin_post', 'company_page', 'job_page', 'news', 'search_result', 'other')),
  title text not null,
  source_url text not null,
  publisher text,
  published_at timestamptz,
  captured_at timestamptz not null default now(),
  excerpt text,
  supports_fields text[] not null default '{}',
  metadata jsonb not null default '{}'::jsonb,
  created_by uuid references public.profiles(id)
);

create index evidence_lead_id_idx on public.evidence(lead_id);
create index evidence_published_at_idx on public.evidence(published_at desc);

create table public.lead_scores (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  icp_version_id uuid not null references public.icp_versions(id),
  score integer not null check (score between 0 and 100),
  disposition text not null check (disposition in ('Strong Fit', 'Good Fit', 'Review', 'Not Qualified', 'Disqualified')),
  tier text not null check (tier in ('Tier 1', 'Tier 2', 'Tier 3', 'Unassigned')),
  persona text,
  hard_stops jsonb not null default '[]'::jsonb,
  evaluations jsonb not null default '[]'::jsonb,
  evidence_ids uuid[] not null default '{}',
  scored_at timestamptz not null default now(),
  scored_by uuid references public.profiles(id)
);

create index lead_scores_lead_id_idx on public.lead_scores(lead_id, scored_at desc);

create table public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  job_type text not null check (job_type in ('enrich', 'research', 'score', 'analyze', 'draft_outreach', 'rescore')),
  status public.processing_status not null default 'queued',
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 3 check (max_attempts > 0),
  payload jsonb not null default '{}'::jsonb,
  result jsonb,
  error_message text,
  run_after timestamptz not null default now(),
  claimed_at timestamptz,
  claimed_by text,
  created_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index processing_jobs_claim_idx
  on public.processing_jobs(status, run_after, created_at);

create table public.outreach_drafts (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  sequence_step integer not null check (sequence_step between 1 and 6),
  channel text not null default 'linkedin' check (channel in ('linkedin', 'email')),
  subject text,
  body text not null,
  status public.outreach_status not null default 'draft',
  evidence_ids uuid[] not null default '{}',
  created_by uuid references public.profiles(id),
  reviewed_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  unique (lead_id, channel, sequence_step)
);

create table public.audit_log (
  id bigint generated always as identity primary key,
  actor_id uuid references public.profiles(id),
  action text not null,
  entity_type text not null,
  entity_id text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger profiles_set_updated_at before update on public.profiles
for each row execute function public.set_updated_at();
create trigger leads_set_updated_at before update on public.leads
for each row execute function public.set_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    coalesce(new.email, ''),
    new.raw_user_meta_data ->> 'full_name',
    new.raw_user_meta_data ->> 'avatar_url'
  );
  return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create or replace function public.current_app_role()
returns public.app_role
language sql
stable
security definer
set search_path = ''
as $$
  select role from public.profiles where id = auth.uid() and is_active = true;
$$;

create or replace function public.is_manager_or_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce(public.current_app_role() in ('admin', 'manager'), false);
$$;

create or replace function public.can_access_lead(target_lead_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.leads
    where id = target_lead_id
      and (
        public.is_manager_or_admin()
        or assigned_to = auth.uid()
        or created_by = auth.uid()
      )
  );
$$;

create or replace function public.set_user_role(target_user_id uuid, new_role public.app_role)
returns public.profiles
language plpgsql
security definer
set search_path = ''
as $$
declare updated_profile public.profiles;
begin
  if public.current_app_role() <> 'admin' then
    raise exception 'Admin role required';
  end if;
  update public.profiles set role = new_role where id = target_user_id returning * into updated_profile;
  if updated_profile.id is null then raise exception 'Profile not found'; end if;
  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (auth.uid(), 'role_changed', 'profile', target_user_id::text, jsonb_build_object('role', new_role));
  return updated_profile;
end;
$$;

create or replace function public.publish_icp_version(target_id uuid)
returns public.icp_versions
language plpgsql
security definer
set search_path = ''
as $$
declare published public.icp_versions;
begin
  if public.current_app_role() <> 'admin' then
    raise exception 'Admin role required';
  end if;
  if not exists (select 1 from public.icp_versions where id = target_id and status = 'draft') then
    raise exception 'Draft ICP version not found';
  end if;
  update public.icp_versions set status = 'archived', archived_at = now()
    where status = 'active';
  update public.icp_versions
    set status = 'active', approved_by = auth.uid(), published_at = now(), archived_at = null
    where id = target_id returning * into published;
  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (auth.uid(), 'icp_published', 'icp_version', target_id::text, jsonb_build_object('version', published.version));
  return published;
end;
$$;

alter table public.profiles enable row level security;
alter table public.icp_versions enable row level security;
alter table public.imports enable row level security;
alter table public.leads enable row level security;
alter table public.evidence enable row level security;
alter table public.lead_scores enable row level security;
alter table public.processing_jobs enable row level security;
alter table public.outreach_drafts enable row level security;
alter table public.audit_log enable row level security;

create policy profiles_select on public.profiles for select to authenticated
using (id = auth.uid() or public.is_manager_or_admin());
create policy profiles_update_self on public.profiles for update to authenticated
using (id = auth.uid()) with check (id = auth.uid());

revoke update on public.profiles from authenticated;
grant update (full_name, avatar_url) on public.profiles to authenticated;
grant execute on function public.set_user_role(uuid, public.app_role) to authenticated;

create policy icp_select on public.icp_versions for select to authenticated using (true);
create policy icp_insert_draft on public.icp_versions for insert to authenticated
with check (
  public.is_manager_or_admin()
  and status = 'draft'
  and created_by = auth.uid()
  and approved_by is null
  and published_at is null
);
create policy icp_update_draft on public.icp_versions for update to authenticated
using (
  status = 'draft'
  and (created_by = auth.uid() or public.current_app_role() = 'admin')
)
with check (
  status = 'draft'
  and (created_by = auth.uid() or public.current_app_role() = 'admin')
  and approved_by is null
  and published_at is null
);

create policy imports_select on public.imports for select to authenticated
using (public.is_manager_or_admin() or created_by = auth.uid());
create policy imports_insert on public.imports for insert to authenticated
with check (created_by = auth.uid());
create policy imports_update on public.imports for update to authenticated
using (public.is_manager_or_admin() or created_by = auth.uid())
with check (public.is_manager_or_admin() or created_by = auth.uid());

create policy leads_select on public.leads for select to authenticated
using (public.is_manager_or_admin() or assigned_to = auth.uid() or created_by = auth.uid());
create policy leads_insert on public.leads for insert to authenticated
with check (created_by = auth.uid() and (assigned_to is null or assigned_to = auth.uid() or public.is_manager_or_admin()));
create policy leads_update on public.leads for update to authenticated
using (public.is_manager_or_admin() or assigned_to = auth.uid() or created_by = auth.uid())
with check (public.is_manager_or_admin() or assigned_to = auth.uid() or created_by = auth.uid());

create policy evidence_select on public.evidence for select to authenticated
using (public.can_access_lead(lead_id));
create policy evidence_insert on public.evidence for insert to authenticated
with check (public.can_access_lead(lead_id));
create policy evidence_update on public.evidence for update to authenticated
using (public.can_access_lead(lead_id)) with check (public.can_access_lead(lead_id));

create policy scores_select on public.lead_scores for select to authenticated
using (public.can_access_lead(lead_id));

create policy jobs_select on public.processing_jobs for select to authenticated
using (public.can_access_lead(lead_id));

create policy drafts_select on public.outreach_drafts for select to authenticated
using (public.can_access_lead(lead_id));
create policy drafts_insert on public.outreach_drafts for insert to authenticated
with check (public.can_access_lead(lead_id));
create policy drafts_update on public.outreach_drafts for update to authenticated
using (public.can_access_lead(lead_id)) with check (public.can_access_lead(lead_id));

create policy audit_select on public.audit_log for select to authenticated
using (public.current_app_role() = 'admin');

revoke all on function public.set_user_role(uuid, public.app_role) from public;
revoke all on function public.publish_icp_version(uuid) from public;
grant execute on function public.publish_icp_version(uuid) to authenticated;

commit;
