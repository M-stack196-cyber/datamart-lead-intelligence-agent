begin;

create or replace function public.can_access_lead(target_lead_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.leads
    where id = target_lead_id
      and (
        public.is_manager_or_admin()
        or (
          assigned_to = auth.uid()
          and sales_approved_at is not null
          and status <> 'disqualified'
        )
      )
  );
$$;

drop policy if exists leads_select on public.leads;
create policy leads_select on public.leads
for select to authenticated
using (
  public.is_manager_or_admin()
  or (
    assigned_to = auth.uid()
    and sales_approved_at is not null
    and status <> 'disqualified'
  )
);

create or replace function public.update_lead(
  target_id uuid,
  next_company_name text,
  next_person_name text,
  next_title text,
  next_linkedin_url text,
  next_company_url text,
  next_email text,
  next_country text,
  next_industry text,
  next_status public.lead_status
)
returns public.leads
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  actor_role public.app_role := public.current_app_role();
  existing_lead public.leads;
  updated_lead public.leads;
begin
  if actor_id is null or actor_role is null then
    raise exception 'Authentication required';
  end if;

  select * into existing_lead
  from public.leads
  where id = target_id
  for update;
  if existing_lead.id is null then
    raise exception 'Lead not found';
  end if;
  if actor_role = 'sales' and not (
    existing_lead.assigned_to = actor_id
    and existing_lead.sales_approved_at is not null
    and existing_lead.status <> 'disqualified'
  ) then
    raise exception 'Sales can edit only assigned, approved leads';
  end if;
  if next_status is distinct from existing_lead.status then
    raise exception 'Lead status changes require the audited review workflow';
  end if;
  if nullif(trim(next_company_name), '') is null
     and nullif(trim(next_linkedin_url), '') is null
     and nullif(trim(next_company_url), '') is null then
    raise exception 'A company name, LinkedIn URL, or company URL is required';
  end if;
  if nullif(trim(next_linkedin_url), '') is not null
     and nullif(trim(next_linkedin_url), '') !~* '^https?://([a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_%\-]+/?([?#].*)?$' then
    raise exception 'Invalid LinkedIn profile URL';
  end if;

  update public.leads
  set company_name = nullif(trim(next_company_name), ''),
      person_name = nullif(trim(next_person_name), ''),
      title = nullif(trim(next_title), ''),
      linkedin_url = nullif(trim(next_linkedin_url), ''),
      company_url = nullif(trim(next_company_url), ''),
      email = nullif(lower(trim(next_email)), ''),
      country = nullif(trim(next_country), ''),
      industry = nullif(trim(next_industry), '')
  where id = target_id
  returning * into updated_lead;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    'lead_updated',
    'lead',
    target_id::text,
    jsonb_build_object('status', updated_lead.status, 'assigned_to', updated_lead.assigned_to)
  );
  return updated_lead;
end;
$$;

create or replace function public.set_lead_review_outcome(
  target_id uuid,
  outcome text,
  reason text
)
returns public.leads
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  existing_lead public.leads;
  updated_lead public.leads;
  latest_score public.lead_scores;
  audit_action text;
begin
  if actor_id is null or public.current_app_role() <> 'admin' then
    raise exception 'Admin role required';
  end if;
  if outcome not in ('disqualified', 'nurture') then
    raise exception 'Review outcome must be disqualified or nurture';
  end if;
  if nullif(trim(reason), '') is null then
    raise exception 'A review reason is required';
  end if;

  select * into existing_lead
  from public.leads
  where id = target_id
  for update;
  if existing_lead.id is null then
    raise exception 'Lead not found';
  end if;

  select * into latest_score
  from public.lead_scores
  where lead_id = target_id
  order by scored_at desc
  limit 1;

  update public.leads
  set status = outcome::public.lead_status,
      assigned_to = case when outcome = 'disqualified' then null else assigned_to end,
      sales_approved_at = null,
      sales_approved_by = null
  where id = target_id
  returning * into updated_lead;

  audit_action := case
    when outcome = 'disqualified' then 'lead_disqualified'
    else 'lead_moved_to_nurture'
  end;
  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    audit_action,
    'lead',
    target_id::text,
    jsonb_build_object(
      'reason', trim(reason),
      'previous_status', existing_lead.status,
      'score', latest_score.score,
      'disposition', latest_score.disposition
    )
  );
  return updated_lead;
end;
$$;

revoke all on function public.can_access_lead(uuid) from public, anon;
grant execute on function public.can_access_lead(uuid) to authenticated;
revoke all on function public.set_lead_review_outcome(uuid, text, text)
  from public, anon;
grant execute on function public.set_lead_review_outcome(uuid, text, text)
  to authenticated;

commit;
