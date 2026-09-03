begin;

create table public.email_delivery_attempts (
  id uuid primary key default gen_random_uuid(),
  outreach_draft_id uuid not null references public.outreach_drafts(id) on delete restrict,
  lead_id uuid not null references public.leads(id) on delete restrict,
  attempted_by uuid not null references public.profiles(id),
  sender_email text not null,
  recipient_email text not null,
  status text not null default 'pending' check (status in ('pending', 'sent', 'failed')),
  provider_message_id text,
  error_message text,
  attempted_at timestamptz not null default now(),
  completed_at timestamptz,
  sent_at timestamptz
);

create index email_delivery_attempts_lead_idx
  on public.email_delivery_attempts(lead_id, attempted_at desc);
create index email_delivery_attempts_draft_idx
  on public.email_delivery_attempts(outreach_draft_id, attempted_at desc);

alter table public.email_delivery_attempts enable row level security;
create policy email_delivery_attempts_select on public.email_delivery_attempts
for select to authenticated
using (
  public.is_manager_or_admin()
  or (attempted_by = auth.uid() and public.can_access_lead(lead_id))
);

revoke all on table public.email_delivery_attempts from anon, authenticated;
grant select on table public.email_delivery_attempts to authenticated;

create or replace function public.begin_email_delivery_attempt(
  target_draft_id uuid,
  actor_id uuid,
  sender_email text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.profiles;
  approved_draft public.outreach_drafts;
  target_lead public.leads;
  attempt public.email_delivery_attempts;
begin
  select * into actor
  from public.profiles
  where id = actor_id and is_active = true;
  if actor.id is null or actor.role not in ('admin', 'manager', 'sales') then
    raise exception 'Authorized active user required';
  end if;

  select * into approved_draft
  from public.outreach_drafts
  where id = target_draft_id
  for update;
  if approved_draft.id is null
     or approved_draft.status <> 'approved'
     or approved_draft.channel <> 'email' then
    raise exception 'An approved email draft is required';
  end if;

  select * into target_lead
  from public.leads
  where id = approved_draft.lead_id
  for update;
  if target_lead.id is null
     or target_lead.status = 'disqualified'
     or target_lead.sales_approved_at is null
     or target_lead.assigned_to is null then
    raise exception 'Lead must be approved and assigned for sales';
  end if;
  if actor.role = 'sales' and target_lead.assigned_to <> actor_id then
    raise exception 'Sales user is not assigned to this lead';
  end if;
  if target_lead.email is null
     or target_lead.email !~* '^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$' then
    raise exception 'A valid lead email address is required';
  end if;
  if sender_email is null
     or sender_email !~* '^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$' then
    raise exception 'A valid configured sender email is required';
  end if;

  insert into public.email_delivery_attempts (
    outreach_draft_id, lead_id, attempted_by, sender_email, recipient_email
  ) values (
    approved_draft.id, target_lead.id, actor_id,
    lower(sender_email), lower(target_lead.email)
  ) returning * into attempt;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    'email_send_attempted',
    'email_delivery_attempt',
    attempt.id::text,
    jsonb_build_object(
      'lead_id', target_lead.id,
      'draft_id', approved_draft.id,
      'recipient', lower(target_lead.email)
    )
  );

  return jsonb_build_object(
    'attempt_id', attempt.id,
    'sender', attempt.sender_email,
    'recipient', attempt.recipient_email,
    'subject', approved_draft.subject,
    'body', approved_draft.body
  );
end;
$$;

create or replace function public.finish_email_delivery_attempt(
  target_attempt_id uuid,
  succeeded boolean,
  provider_message_id text,
  safe_error text,
  actor_id uuid
)
returns public.email_delivery_attempts
language plpgsql
security definer
set search_path = ''
as $$
declare
  completed_attempt public.email_delivery_attempts;
begin
  update public.email_delivery_attempts
  set status = case when succeeded then 'sent' else 'failed' end,
      provider_message_id = case when succeeded then nullif(trim(provider_message_id), '') else null end,
      error_message = case when succeeded then null else left(coalesce(safe_error, 'Gmail provider request failed'), 500) end,
      completed_at = now(),
      sent_at = case when succeeded then now() else null end
  where id = target_attempt_id
    and attempted_by = actor_id
    and status = 'pending'
  returning * into completed_attempt;
  if completed_attempt.id is null then
    raise exception 'Pending email delivery attempt not found';
  end if;
  if succeeded and completed_attempt.provider_message_id is null then
    raise exception 'Successful Gmail delivery requires a provider message ID';
  end if;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    case when succeeded then 'email_send_succeeded' else 'email_send_failed' end,
    'email_delivery_attempt',
    completed_attempt.id::text,
    jsonb_build_object(
      'lead_id', completed_attempt.lead_id,
      'draft_id', completed_attempt.outreach_draft_id,
      'status', completed_attempt.status,
      'provider_message_id', completed_attempt.provider_message_id,
      'error', completed_attempt.error_message
    )
  );
  return completed_attempt;
end;
$$;

revoke all on function public.begin_email_delivery_attempt(uuid, uuid, text)
  from public, anon, authenticated;
grant execute on function public.begin_email_delivery_attempt(uuid, uuid, text)
  to service_role;
revoke all on function public.finish_email_delivery_attempt(uuid, boolean, text, text, uuid)
  from public, anon, authenticated;
grant execute on function public.finish_email_delivery_attempt(uuid, boolean, text, text, uuid)
  to service_role;

commit;
