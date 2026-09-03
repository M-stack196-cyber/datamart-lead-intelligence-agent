begin;

create type public.outbound_lifecycle_status as enum (
  'draft',
  'approved',
  'scheduled',
  'sent',
  'replied',
  'paused',
  'completed',
  'failed'
);

create type public.outbound_direction as enum ('outbound', 'inbound');
create type public.crm_sync_status as enum ('pending', 'synced', 'failed', 'skipped');
create type public.suppression_kind as enum ('unsubscribed', 'manual', 'permanent');

create table public.outreach_sequences (
  id uuid primary key default gen_random_uuid(),
  external_id text not null unique,
  name text not null,
  description text,
  channel text not null default 'email' check (channel in ('email')),
  is_enabled boolean not null default true,
  created_by uuid references public.profiles(id),
  updated_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.outreach_sequence_steps (
  id uuid primary key default gen_random_uuid(),
  sequence_id uuid not null references public.outreach_sequences(id) on delete cascade,
  step_number integer not null check (step_number > 0),
  delay_days integer not null default 0 check (delay_days >= 0),
  subject_template text not null,
  message_template text not null,
  is_enabled boolean not null default true,
  created_by uuid references public.profiles(id),
  updated_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (sequence_id, step_number)
);

create table public.lead_outreach (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  sequence_id uuid not null references public.outreach_sequences(id) on delete restrict,
  status public.outbound_lifecycle_status not null default 'draft',
  current_step_number integer not null default 1 check (current_step_number > 0),
  next_run_at timestamptz not null default now(),
  provider_thread_id text,
  paused_reason text,
  last_error text,
  created_by uuid references public.profiles(id),
  updated_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (lead_id, sequence_id)
);

create table public.outreach_messages (
  id uuid primary key default gen_random_uuid(),
  lead_outreach_id uuid not null references public.lead_outreach(id) on delete cascade,
  sequence_step_id uuid references public.outreach_sequence_steps(id) on delete set null,
  step_number integer check (step_number > 0),
  direction public.outbound_direction not null default 'outbound',
  status public.outbound_lifecycle_status not null default 'draft',
  subject text,
  body text not null,
  generation_provider text not null default 'mock',
  generation_model text,
  provider_message_id text,
  idempotency_key text not null unique,
  error_message text,
  provider_response jsonb not null default '{}'::jsonb,
  generated_at timestamptz not null default now(),
  approved_at timestamptz,
  scheduled_at timestamptz,
  sent_at timestamptz,
  replied_at timestamptz,
  created_by uuid references public.profiles(id),
  updated_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (lead_outreach_id, step_number, direction)
);

alter table public.lead_outreach
  add column if not exists latest_message_id uuid references public.outreach_messages(id) on delete set null;

create table public.outreach_events (
  id uuid primary key default gen_random_uuid(),
  lead_outreach_id uuid not null references public.lead_outreach(id) on delete cascade,
  message_id uuid references public.outreach_messages(id) on delete set null,
  event_type text not null,
  event_payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  created_by uuid references public.profiles(id)
);

create index outreach_events_lead_outreach_idx
  on public.outreach_events(lead_outreach_id, occurred_at desc);
create index outreach_messages_outreach_idx
  on public.outreach_messages(lead_outreach_id, generated_at desc);
create index outreach_messages_status_idx
  on public.outreach_messages(status, direction, generated_at desc);

create table public.suppression_entries (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  normalized_email text generated always as (lower(btrim(email))) stored,
  suppression_kind public.suppression_kind not null,
  reason text,
  source text not null default 'manual',
  is_active boolean not null default true,
  created_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (normalized_email)
);

create table public.crm_sync_state (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  lead_outreach_id uuid references public.lead_outreach(id) on delete set null,
  provider_key text not null,
  external_crm_id text,
  sync_status public.crm_sync_status not null default 'pending',
  mapping jsonb not null default '{}'::jsonb,
  error_message text,
  synced_at timestamptz,
  next_sync_at timestamptz not null default now(),
  created_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (lead_id, provider_key)
);

create index crm_sync_state_provider_idx
  on public.crm_sync_state(provider_key, sync_status, next_sync_at);
create index crm_sync_state_lead_idx
  on public.crm_sync_state(lead_id, created_at desc);

drop trigger if exists outreach_sequences_set_updated_at on public.outreach_sequences;
create trigger outreach_sequences_set_updated_at
before update on public.outreach_sequences
for each row execute function public.set_updated_at();

drop trigger if exists outreach_sequence_steps_set_updated_at on public.outreach_sequence_steps;
create trigger outreach_sequence_steps_set_updated_at
before update on public.outreach_sequence_steps
for each row execute function public.set_updated_at();

drop trigger if exists lead_outreach_set_updated_at on public.lead_outreach;
create trigger lead_outreach_set_updated_at
before update on public.lead_outreach
for each row execute function public.set_updated_at();

drop trigger if exists outreach_messages_set_updated_at on public.outreach_messages;
create trigger outreach_messages_set_updated_at
before update on public.outreach_messages
for each row execute function public.set_updated_at();

drop trigger if exists suppression_entries_set_updated_at on public.suppression_entries;
create trigger suppression_entries_set_updated_at
before update on public.suppression_entries
for each row execute function public.set_updated_at();

drop trigger if exists crm_sync_state_set_updated_at on public.crm_sync_state;
create trigger crm_sync_state_set_updated_at
before update on public.crm_sync_state
for each row execute function public.set_updated_at();

alter table public.outreach_sequences enable row level security;
alter table public.outreach_sequence_steps enable row level security;
alter table public.lead_outreach enable row level security;
alter table public.outreach_messages enable row level security;
alter table public.outreach_events enable row level security;
alter table public.suppression_entries enable row level security;
alter table public.crm_sync_state enable row level security;

drop policy if exists sequences_select on public.outreach_sequences;
create policy sequences_select on public.outreach_sequences
for select to authenticated
using (public.is_manager_or_admin() or is_enabled = true);

drop policy if exists sequences_manage on public.outreach_sequences;
create policy sequences_manage on public.outreach_sequences
for insert to authenticated
with check (public.is_manager_or_admin());
drop policy if exists sequences_update on public.outreach_sequences;
create policy sequences_update on public.outreach_sequences
for update to authenticated
using (public.is_manager_or_admin())
with check (public.is_manager_or_admin());
drop policy if exists sequences_delete on public.outreach_sequences;
create policy sequences_delete on public.outreach_sequences
for delete to authenticated
using (public.is_manager_or_admin());

drop policy if exists sequence_steps_select on public.outreach_sequence_steps;
create policy sequence_steps_select on public.outreach_sequence_steps
for select to authenticated
using (
  exists (
    select 1 from public.outreach_sequences as sequence
    where sequence.id = sequence_id
      and (public.is_manager_or_admin() or sequence.is_enabled = true)
  )
);

drop policy if exists sequence_steps_manage on public.outreach_sequence_steps;
create policy sequence_steps_manage on public.outreach_sequence_steps
for insert to authenticated
with check (public.is_manager_or_admin());
drop policy if exists sequence_steps_update on public.outreach_sequence_steps;
create policy sequence_steps_update on public.outreach_sequence_steps
for update to authenticated
using (public.is_manager_or_admin())
with check (public.is_manager_or_admin());
drop policy if exists sequence_steps_delete on public.outreach_sequence_steps;
create policy sequence_steps_delete on public.outreach_sequence_steps
for delete to authenticated
using (public.is_manager_or_admin());

drop policy if exists lead_outreach_select on public.lead_outreach;
create policy lead_outreach_select on public.lead_outreach
for select to authenticated
using (public.can_access_lead(lead_id));

drop policy if exists lead_outreach_manage on public.lead_outreach;
create policy lead_outreach_manage on public.lead_outreach
for insert to authenticated
with check (public.is_manager_or_admin());
drop policy if exists lead_outreach_update on public.lead_outreach;
create policy lead_outreach_update on public.lead_outreach
for update to authenticated
using (public.can_access_lead(lead_id) or public.is_manager_or_admin())
with check (public.can_access_lead(lead_id) or public.is_manager_or_admin());

drop policy if exists outreach_messages_select on public.outreach_messages;
create policy outreach_messages_select on public.outreach_messages
for select to authenticated
using (
  exists (
    select 1
    from public.lead_outreach as outreach
    where outreach.id = lead_outreach_id
      and public.can_access_lead(outreach.lead_id)
  )
);

drop policy if exists outreach_events_select on public.outreach_events;
create policy outreach_events_select on public.outreach_events
for select to authenticated
using (
  exists (
    select 1
    from public.lead_outreach as outreach
    where outreach.id = lead_outreach_id
      and public.can_access_lead(outreach.lead_id)
  )
);

drop policy if exists suppression_entries_select on public.suppression_entries;
create policy suppression_entries_select on public.suppression_entries
for select to authenticated
using (public.is_manager_or_admin());

drop policy if exists suppression_entries_manage on public.suppression_entries;
create policy suppression_entries_manage on public.suppression_entries
for insert to authenticated
with check (public.is_manager_or_admin());
drop policy if exists suppression_entries_update on public.suppression_entries;
create policy suppression_entries_update on public.suppression_entries
for update to authenticated
using (public.is_manager_or_admin())
with check (public.is_manager_or_admin());
drop policy if exists suppression_entries_delete on public.suppression_entries;
create policy suppression_entries_delete on public.suppression_entries
for delete to authenticated
using (public.is_manager_or_admin());

drop policy if exists crm_sync_state_select on public.crm_sync_state;
create policy crm_sync_state_select on public.crm_sync_state
for select to authenticated
using (
  exists (
    select 1 from public.leads as lead
    where lead.id = lead_id
      and public.can_access_lead(lead.id)
  )
);

drop policy if exists crm_sync_state_manage on public.crm_sync_state;
create policy crm_sync_state_manage on public.crm_sync_state
for insert to authenticated
with check (public.is_manager_or_admin());
drop policy if exists crm_sync_state_update on public.crm_sync_state;
create policy crm_sync_state_update on public.crm_sync_state
for update to authenticated
using (public.is_manager_or_admin())
with check (public.is_manager_or_admin());

revoke all on table public.outreach_sequences from anon, authenticated;
revoke all on table public.outreach_sequence_steps from anon, authenticated;
revoke all on table public.lead_outreach from anon, authenticated;
revoke all on table public.outreach_messages from anon, authenticated;
revoke all on table public.outreach_events from anon, authenticated;
revoke all on table public.suppression_entries from anon, authenticated;
revoke all on table public.crm_sync_state from anon, authenticated;

grant select on table public.outreach_sequences to authenticated;
grant select on table public.outreach_sequence_steps to authenticated;
grant select on table public.lead_outreach to authenticated;
grant select on table public.outreach_messages to authenticated;
grant select on table public.outreach_events to authenticated;
grant select on table public.suppression_entries to authenticated;
grant select on table public.crm_sync_state to authenticated;

create or replace function public.is_email_suppressed(target_email text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.suppression_entries
    where normalized_email = lower(btrim(target_email))
      and is_active = true
  );
$$;

revoke all on function public.is_email_suppressed(text) from public, anon, authenticated;
grant execute on function public.is_email_suppressed(text) to service_role;

with seed_sequence as (
  insert into public.outreach_sequences (
    external_id, name, description, channel, is_enabled, created_by, updated_by
  ) values (
    'datamart-outbound-sequence-v1',
    'Datamart Outreach Sequence',
    'MVP outbound email sequence for approved sales leads.',
    'email',
    true,
    null,
    null
  )
  on conflict (external_id) do update
  set name = excluded.name,
      description = excluded.description,
      channel = excluded.channel,
      is_enabled = excluded.is_enabled,
      updated_at = now()
  returning id
)
insert into public.outreach_sequence_steps (
  sequence_id, step_number, delay_days, subject_template, message_template, is_enabled, created_by, updated_by
)
select
  seed_sequence.id,
  step_number,
  delay_days,
  subject_template,
  message_template,
  true,
  null,
  null
from seed_sequence
join (
  values
    (1, 0, 'A brief question about {{company_name}}', 'Hi {{first_name}}, I reviewed the stored evidence for {{company_name}} and wanted to ask whether Datamart could help with the priorities already identified.'),
    (2, 3, 'Following up on {{company_name}}', 'Just following up on the earlier note. The evidence we have on {{company_name}} still suggests there may be a fit worth discussing.'),
    (3, 7, 'One more follow-up for {{company_name}}', 'I wanted to send one more brief follow-up in case this is still on your radar.'),
    (4, 14, 'Closing the loop on {{company_name}}', 'I will close the loop after this note, but I am happy to reconnect if the timing becomes better.')
) as steps(step_number, delay_days, subject_template, message_template) on true
on conflict (sequence_id, step_number) do update
set delay_days = excluded.delay_days,
    subject_template = excluded.subject_template,
    message_template = excluded.message_template,
    is_enabled = excluded.is_enabled,
    updated_at = now();

commit;