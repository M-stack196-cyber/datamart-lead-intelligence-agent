begin;

-- Lead mutations are performed through the audited functions below. This keeps
-- assignment and deletion decisions outside caller-controlled browser updates.
revoke insert, update, delete on table public.leads from authenticated;

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
  existing_lead public.leads;
  updated_lead public.leads;
begin
  if actor_id is null or public.current_app_role() is null then
    raise exception 'Authentication required';
  end if;

  select * into existing_lead from public.leads where id = target_id;
  if existing_lead.id is null then
    raise exception 'Lead not found';
  end if;
  if not (
    public.is_manager_or_admin()
    or existing_lead.assigned_to = actor_id
    or existing_lead.created_by = actor_id
  ) then
    raise exception 'You do not have permission to edit this lead';
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
      industry = nullif(trim(next_industry), ''),
      status = next_status
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

create or replace function public.assign_lead(target_id uuid, assignee_id uuid)
returns public.leads
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  assignee public.profiles;
  updated_lead public.leads;
begin
  if actor_id is null or not public.is_manager_or_admin() then
    raise exception 'Manager or admin role required';
  end if;

  select * into assignee from public.profiles where id = assignee_id and is_active = true;
  if assignee.id is null or assignee.role <> 'sales' then
    raise exception 'Lead assignee must be an active sales user';
  end if;

  update public.leads
  set assigned_to = assignee_id
  where id = target_id and status <> 'disqualified' and assigned_to is distinct from assignee_id
  returning * into updated_lead;
  if updated_lead.id is null then
    raise exception 'Lead must be approved for sales and cannot be disqualified';
  end if;
  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (actor_id, 'lead_assigned', 'lead', target_id::text, jsonb_build_object('assigned_to', assignee_id));
  return updated_lead;
end;
$$;

create or replace function public.delete_lead(target_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  existing_lead public.leads;
begin
  if actor_id is null or public.current_app_role() <> 'admin' then
    raise exception 'Admin role required';
  end if;
  select * into existing_lead from public.leads where id = target_id;
  if existing_lead.id is null then
    raise exception 'Lead not found';
  end if;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    'lead_deleted',
    'lead',
    target_id::text,
    jsonb_build_object(
      'company_name', existing_lead.company_name,
      'person_name', existing_lead.person_name,
      'linkedin_url', existing_lead.linkedin_url,
      'import_id', existing_lead.import_id,
      'assigned_to', existing_lead.assigned_to
    )
  );
  delete from public.leads where id = target_id;
end;
$$;

revoke all on function public.update_lead(uuid, text, text, text, text, text, text, text, text, public.lead_status) from public, anon;
revoke all on function public.assign_lead(uuid, uuid) from public, anon;
revoke all on function public.delete_lead(uuid) from public, anon;
grant execute on function public.update_lead(uuid, text, text, text, text, text, text, text, text, public.lead_status) to authenticated;
grant execute on function public.assign_lead(uuid, uuid) to authenticated;
grant execute on function public.delete_lead(uuid) to authenticated;

commit;
