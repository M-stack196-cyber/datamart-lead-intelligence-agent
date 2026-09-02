begin;

-- A lead must be explicitly approved before sales assignment or export.
alter table public.leads
  add column if not exists sales_approved_at timestamptz,
  add column if not exists sales_approved_by uuid references public.profiles(id);

create index if not exists leads_sales_approved_idx
  on public.leads(sales_approved_at) where sales_approved_at is not null;

create or replace function public.approve_lead_for_sales(target_id uuid)
returns public.leads
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  latest_score public.lead_scores;
  updated_lead public.leads;
begin
  if actor_id is null or public.current_app_role() <> 'admin' then
    raise exception 'Admin role required';
  end if;

  select * into latest_score from public.lead_scores
  where lead_id = target_id order by scored_at desc limit 1;
  if latest_score.id is null then
    raise exception 'A scored lead is required before sales approval';
  end if;
  if coalesce(jsonb_array_length(latest_score.hard_stops), 0) > 0
     or latest_score.disposition not in ('Strong Fit', 'Good Fit') then
    raise exception 'Only a scored qualified lead without hard stops can be approved';
  end if;

  update public.leads
  set sales_approved_at = now(), sales_approved_by = actor_id,
      status = 'qualified'
  where id = target_id and status <> 'disqualified'
  returning * into updated_lead;
  if updated_lead.id is null then raise exception 'Lead not found or disqualified'; end if;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (actor_id, 'lead_approved_for_sales', 'lead', target_id::text,
    jsonb_build_object('score', latest_score.score, 'disposition', latest_score.disposition));
  return updated_lead;
end;
$$;

create or replace function public.assign_lead(target_id uuid, assignee_id uuid)
returns public.leads
language plpgsql
security definer
set search_path = ''
as $$
declare actor_id uuid := auth.uid(); assignee public.profiles; updated_lead public.leads;
begin
  if actor_id is null or not public.is_manager_or_admin() then raise exception 'Manager or admin role required'; end if;
  select * into assignee from public.profiles where id = assignee_id and is_active = true;
  if assignee.id is null or assignee.role <> 'sales' then raise exception 'Lead assignee must be an active sales user'; end if;
  update public.leads set assigned_to = assignee_id
  where id = target_id and status <> 'disqualified' and sales_approved_at is not null
  returning * into updated_lead;
  if updated_lead.id is null then raise exception 'Lead must be approved for sales and cannot be disqualified'; end if;
  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (actor_id, 'lead_assigned', 'lead', target_id::text, jsonb_build_object('assigned_to', assignee_id));
  return updated_lead;
end;
$$;

revoke all on function public.approve_lead_for_sales(uuid) from public, anon;
grant execute on function public.approve_lead_for_sales(uuid) to authenticated;
revoke all on function public.assign_lead(uuid, uuid) from public, anon;
grant execute on function public.assign_lead(uuid, uuid) to authenticated;

commit;
