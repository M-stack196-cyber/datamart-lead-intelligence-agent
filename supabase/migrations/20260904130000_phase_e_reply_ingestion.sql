begin;

do $$
begin
  if not exists (
    select 1
    from pg_type
    where typname = 'reply_classification'
  ) then
    create type public.reply_classification as enum (
      'interested',
      'not_interested',
      'question',
      'meeting_request',
      'objection',
      'unsubscribe',
      'out_of_office',
      'unknown'
    );
  end if;
end
$$;

-- The original Phase A constraint allowed only one message
-- per outreach step + direction. That is correct for outbound
-- messages, but prospects may send multiple inbound replies.
alter table public.outreach_messages
  drop constraint if exists
  outreach_messages_lead_outreach_id_step_number_direction_key;

create unique index if not exists
  outreach_messages_outbound_step_unique
  on public.outreach_messages(
    lead_outreach_id,
    step_number,
    direction
  )
  where direction = 'outbound';

create table if not exists public.inbound_reply_events (
  id uuid primary key default gen_random_uuid(),

  lead_id uuid not null
    references public.leads(id)
    on delete cascade,

  lead_outreach_id uuid not null
    references public.lead_outreach(id)
    on delete cascade,

  outreach_message_id uuid
    references public.outreach_messages(id)
    on delete set null,

  provider_name text not null,

  provider_message_id text,

  thread_id text,

  dedupe_key text not null unique,

  from_email text not null,

  to_email text not null,

  subject text not null default '',

  body text not null,

  classification public.reply_classification
    not null
    default 'unknown',

  classification_reason text,

  is_unsubscribe boolean
    not null
    default false,

  received_at timestamptz not null,

  metadata jsonb not null
    default '{}'::jsonb,

  created_at timestamptz not null
    default now()
);

create unique index if not exists
  inbound_reply_provider_message_unique
  on public.inbound_reply_events(
    provider_name,
    provider_message_id
  )
  where provider_message_id is not null;

create index if not exists
  inbound_reply_lead_idx
  on public.inbound_reply_events(
    lead_id,
    received_at desc
  );

create index if not exists
  inbound_reply_outreach_idx
  on public.inbound_reply_events(
    lead_outreach_id,
    received_at desc
  );

create index if not exists
  inbound_reply_classification_idx
  on public.inbound_reply_events(
    classification,
    received_at desc
  );

alter table public.inbound_reply_events
  enable row level security;

drop policy if exists
  inbound_reply_events_select
  on public.inbound_reply_events;

create policy inbound_reply_events_select
  on public.inbound_reply_events
  for select
  to authenticated
  using (
    public.can_access_lead(lead_id)
  );

commit;
