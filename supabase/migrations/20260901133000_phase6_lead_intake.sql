begin;

alter table public.leads alter column company_name drop not null;
alter table public.leads add constraint leads_identity_required
  check (linkedin_url is not null or company_url is not null or company_name is not null);

create or replace function public.ingest_leads(
  rows jsonb,
  intake_source text default 'profile_links',
  intake_file_name text default 'manual-profile-links'
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid := auth.uid();
  import_record public.imports;
  item jsonb;
  row_number integer := 0;
  accepted_count integer := 0;
  rejected_count integer := 0;
  inserted_lead public.leads;
  errors jsonb := '[]'::jsonb;
  linkedin_value text;
  company_value text;
begin
  if actor_id is null or public.current_app_role() is null then
    raise exception 'Authentication required';
  end if;
  if intake_source not in ('csv', 'profile_links') then
    raise exception 'Unsupported intake source';
  end if;
  if jsonb_typeof(rows) <> 'array' or jsonb_array_length(rows) = 0 then
    raise exception 'At least one lead is required';
  end if;
  if jsonb_array_length(rows) > 100 then
    raise exception 'A single import is limited to 100 leads';
  end if;

  insert into public.imports(file_name, source, status, total_rows, created_by)
  values (left(coalesce(nullif(trim(intake_file_name), ''), 'lead-import'), 255), intake_source, 'processing', jsonb_array_length(rows), actor_id)
  returning * into import_record;

  for item in select value from jsonb_array_elements(rows)
  loop
    row_number := row_number + 1;
    linkedin_value := nullif(trim(item ->> 'linkedin_url'), '');
    company_value := nullif(trim(item ->> 'company_name'), '');

    if linkedin_value is null and company_value is null and nullif(trim(item ->> 'company_url'), '') is null then
      rejected_count := rejected_count + 1;
      errors := errors || jsonb_build_array(jsonb_build_object('row', row_number, 'reason', 'LinkedIn URL, company URL, or company name is required'));
      continue;
    end if;
    if linkedin_value is not null and linkedin_value !~* '^https?://([a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_%\-]+/?([?#].*)?$' then
      rejected_count := rejected_count + 1;
      errors := errors || jsonb_build_array(jsonb_build_object('row', row_number, 'reason', 'Invalid LinkedIn profile URL'));
      continue;
    end if;

    insert into public.leads(
      import_id, created_by, assigned_to, company_name, person_name, title,
      linkedin_url, company_url, email, country, industry, raw_source_data
    ) values (
      import_record.id,
      actor_id,
      case when public.current_app_role() = 'sales' then actor_id else null end,
      company_value,
      nullif(trim(item ->> 'person_name'), ''),
      nullif(trim(item ->> 'title'), ''),
      linkedin_value,
      nullif(trim(item ->> 'company_url'), ''),
      nullif(lower(trim(item ->> 'email')), ''),
      nullif(trim(item ->> 'country'), ''),
      nullif(trim(item ->> 'industry'), ''),
      item
    )
    on conflict (lower(linkedin_url)) where linkedin_url is not null do nothing
    returning * into inserted_lead;

    if inserted_lead.id is null then
      rejected_count := rejected_count + 1;
      errors := errors || jsonb_build_array(jsonb_build_object('row', row_number, 'reason', 'Duplicate LinkedIn profile URL'));
    else
      accepted_count := accepted_count + 1;
      insert into public.processing_jobs(lead_id, job_type, status, payload, created_by)
      values (inserted_lead.id, 'enrich', 'queued', jsonb_build_object('source', intake_source, 'import_id', import_record.id), actor_id);
    end if;
    inserted_lead := null;
  end loop;

  update public.imports
  set status = 'completed', accepted_rows = accepted_count, rejected_rows = rejected_count,
      error_summary = jsonb_build_object('errors', errors), completed_at = now()
  where id = import_record.id;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (actor_id, 'leads_imported', 'import', import_record.id::text,
          jsonb_build_object('accepted', accepted_count, 'rejected', rejected_count, 'source', intake_source));

  return jsonb_build_object(
    'import_id', import_record.id,
    'total', jsonb_array_length(rows),
    'accepted', accepted_count,
    'rejected', rejected_count,
    'errors', errors
  );
end;
$$;

revoke all on function public.ingest_leads(jsonb, text, text) from public, anon;
grant execute on function public.ingest_leads(jsonb, text, text) to authenticated;

commit;
