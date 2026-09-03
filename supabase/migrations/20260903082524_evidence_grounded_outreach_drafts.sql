begin;

alter table public.outreach_drafts
  add column if not exists review_notes text,
  add column if not exists updated_at timestamptz not null default now();

drop trigger if exists outreach_drafts_set_updated_at on public.outreach_drafts;
create trigger outreach_drafts_set_updated_at
before update on public.outreach_drafts
for each row execute function public.set_updated_at();

drop policy if exists drafts_select on public.outreach_drafts;
drop policy if exists drafts_insert on public.outreach_drafts;
drop policy if exists drafts_update on public.outreach_drafts;
create policy drafts_select on public.outreach_drafts
for select to authenticated
using (
  public.is_manager_or_admin()
  or (
    status = 'approved'
    and public.can_access_lead(lead_id)
  )
);

revoke insert, update, delete on table public.outreach_drafts from authenticated;
grant select on table public.outreach_drafts to authenticated;

create or replace function public.create_generated_outreach_draft(
  target_lead_id uuid,
  draft_channel text,
  draft_subject text,
  draft_body text,
  draft_evidence_ids uuid[],
  actor_id uuid
)
returns public.outreach_drafts
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.profiles;
  target_lead public.leads;
  latest_score public.lead_scores;
  stored_draft public.outreach_drafts;
  evidence_count integer;
begin
  select * into actor
  from public.profiles
  where id = actor_id and is_active = true;
  if actor.id is null or actor.role not in ('admin', 'manager') then
    raise exception 'Manager or admin role required';
  end if;
  if draft_channel not in ('email', 'linkedin') then
    raise exception 'Outreach channel must be email or linkedin';
  end if;
  if nullif(trim(draft_body), '') is null or length(draft_body) > 4000 then
    raise exception 'A concise outreach body is required';
  end if;
  if cardinality(draft_evidence_ids) = 0 then
    raise exception 'Stored evidence is required for outreach generation';
  end if;

  select * into target_lead
  from public.leads
  where id = target_lead_id
  for update;
  if target_lead.id is null or target_lead.status = 'disqualified' then
    raise exception 'Lead is not eligible for outreach';
  end if;

  select * into latest_score
  from public.lead_scores
  where lead_id = target_lead_id
  order by scored_at desc
  limit 1;
  if latest_score.id is null
     or coalesce(jsonb_array_length(latest_score.hard_stops), 0) > 0
     or latest_score.disposition in ('Disqualified', 'Not Qualified') then
    raise exception 'An eligible score without hard stops is required';
  end if;

  select count(*) into evidence_count
  from public.evidence
  where lead_id = target_lead_id and id = any(draft_evidence_ids);
  if evidence_count <> cardinality(draft_evidence_ids) then
    raise exception 'Every draft evidence item must belong to the lead';
  end if;

  insert into public.outreach_drafts (
    lead_id, sequence_step, channel, subject, body, status,
    evidence_ids, created_by, reviewed_by, reviewed_at, review_notes
  ) values (
    target_lead_id, 1, draft_channel, nullif(trim(draft_subject), ''),
    draft_body, 'draft', draft_evidence_ids, actor_id, null, null, null
  )
  on conflict (lead_id, channel, sequence_step) do update
  set subject = excluded.subject,
      body = excluded.body,
      evidence_ids = excluded.evidence_ids,
      created_by = excluded.created_by,
      reviewed_by = null,
      reviewed_at = null,
      review_notes = null
  where public.outreach_drafts.status = 'draft'
  returning * into stored_draft;
  if stored_draft.id is null then
    raise exception 'An approved or rejected draft cannot be regenerated';
  end if;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    'outreach_draft_generated',
    'outreach_draft',
    stored_draft.id::text,
    jsonb_build_object(
      'lead_id', target_lead_id,
      'channel', draft_channel,
      'evidence_ids', draft_evidence_ids
    )
  );
  return stored_draft;
end;
$$;

create or replace function public.update_outreach_draft(
  target_draft_id uuid,
  next_subject text,
  next_body text
)
returns public.outreach_drafts
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  updated_draft public.outreach_drafts;
begin
  if actor_id is null or not public.is_manager_or_admin() then
    raise exception 'Manager or admin role required';
  end if;
  if nullif(trim(next_body), '') is null or length(next_body) > 4000 then
    raise exception 'A concise outreach body is required';
  end if;

  update public.outreach_drafts
  set subject = nullif(trim(next_subject), ''),
      body = next_body
  where id = target_draft_id and status = 'draft'
  returning * into updated_draft;
  if updated_draft.id is null then
    raise exception 'Only a draft can be edited';
  end if;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    'outreach_draft_edited',
    'outreach_draft',
    target_draft_id::text,
    jsonb_build_object('lead_id', updated_draft.lead_id, 'channel', updated_draft.channel)
  );
  return updated_draft;
end;
$$;

create or replace function public.review_outreach_draft(
  target_draft_id uuid,
  review_action text,
  notes text,
  actor_id uuid
)
returns public.outreach_drafts
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor public.profiles;
  existing_draft public.outreach_drafts;
  reviewed_draft public.outreach_drafts;
  evidence_count integer;
begin
  select * into actor
  from public.profiles
  where id = actor_id and is_active = true;
  if actor.id is null or actor.role not in ('admin', 'manager') then
    raise exception 'Manager or admin role required';
  end if;
  if review_action not in ('approved', 'rejected') then
    raise exception 'Review action must be approved or rejected';
  end if;
  if review_action = 'approved' and actor.role <> 'admin' then
    raise exception 'Admin role required for outreach approval';
  end if;
  if nullif(trim(notes), '') is null then
    raise exception 'Review notes are required';
  end if;

  select * into existing_draft
  from public.outreach_drafts
  where id = target_draft_id
  for update;
  if existing_draft.id is null or existing_draft.status <> 'draft' then
    raise exception 'Only a draft can be reviewed';
  end if;
  if review_action = 'approved' then
    select count(*) into evidence_count
    from public.evidence
    where lead_id = existing_draft.lead_id
      and id = any(existing_draft.evidence_ids);
    if cardinality(existing_draft.evidence_ids) = 0
       or evidence_count <> cardinality(existing_draft.evidence_ids) then
      raise exception 'Approved outreach requires stored lead evidence';
    end if;
  end if;

  update public.outreach_drafts
  set status = review_action::public.outreach_status,
      reviewed_by = actor_id,
      reviewed_at = now(),
      review_notes = trim(notes)
  where id = target_draft_id
  returning * into reviewed_draft;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    'outreach_draft_' || review_action,
    'outreach_draft',
    target_draft_id::text,
    jsonb_build_object(
      'lead_id', reviewed_draft.lead_id,
      'channel', reviewed_draft.channel,
      'notes', trim(notes)
    )
  );
  return reviewed_draft;
end;
$$;

revoke all on function public.create_generated_outreach_draft(
  uuid, text, text, text, uuid[], uuid
) from public, anon, authenticated;
grant execute on function public.create_generated_outreach_draft(
  uuid, text, text, text, uuid[], uuid
) to service_role;
revoke all on function public.update_outreach_draft(uuid, text, text)
  from public, anon;
grant execute on function public.update_outreach_draft(uuid, text, text)
  to authenticated;
revoke all on function public.review_outreach_draft(uuid, text, text, uuid)
  from public, anon, authenticated;
grant execute on function public.review_outreach_draft(uuid, text, text, uuid)
  to service_role;

commit;
