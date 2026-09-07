begin;

-- Automated provider discoveries do not belong to a human user.
-- Existing manual imports continue storing created_by normally.
alter table public.imports
  alter column created_by drop not null;

alter table public.leads
  alter column created_by drop not null;

create index if not exists leads_email_lookup_idx
  on public.leads(lower(email))
  where email is not null;

create or replace function public.ingest_vibe_discovered_leads(
  rows jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  import_record public.imports;
  item jsonb;
  existing_lead public.leads;
  stored_lead public.leads;
  linkedin_value text;
  email_value text;
  company_value text;
  accepted_count integer := 0;
  updated_count integer := 0;
  rejected_count integer := 0;
  row_number integer := 0;
  errors jsonb := '[]'::jsonb;
  stored_ids jsonb := '[]'::jsonb;
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception 'Service role required';
  end if;

  if jsonb_typeof(rows) <> 'array'
     or jsonb_array_length(rows) = 0 then
    raise exception 'At least one discovered lead is required';
  end if;

  if jsonb_array_length(rows) > 100 then
    raise exception 'A single Vibe discovery batch is limited to 100 leads';
  end if;

  insert into public.imports(
    file_name,
    source,
    status,
    total_rows,
    created_by
  )
  values (
    'automatic-vibe-discovery',
    'vibe',
    'processing',
    jsonb_array_length(rows),
    null
  )
  returning * into import_record;

  for item in
    select value
    from jsonb_array_elements(rows)
  loop
    row_number := row_number + 1;
    existing_lead := null;
    stored_lead := null;

    linkedin_value := nullif(
      trim(item ->> 'linkedin_url'),
      ''
    );

    email_value := nullif(
      lower(trim(item ->> 'email')),
      ''
    );

    company_value := nullif(
      trim(item ->> 'company_name'),
      ''
    );

    if linkedin_value is null
       and email_value is null
       and company_value is null then
      rejected_count := rejected_count + 1;

      errors := errors || jsonb_build_array(
        jsonb_build_object(
          'row',
          row_number,
          'reason',
          'LinkedIn URL, email, or company name is required'
        )
      );

      continue;
    end if;

    -- First preference: stable LinkedIn identity.
    if linkedin_value is not null then
      select *
      into existing_lead
      from public.leads
      where lower(linkedin_url) = lower(linkedin_value)
      limit 1;
    end if;

    -- Second preference: email identity.
    if existing_lead.id is null
       and email_value is not null then
      select *
      into existing_lead
      from public.leads
      where lower(email) = lower(email_value)
      order by created_at
      limit 1;
    end if;

    if existing_lead.id is not null then
      update public.leads
      set
        company_name = coalesce(
          company_value,
          company_name
        ),
        person_name = coalesce(
          nullif(trim(item ->> 'person_name'), ''),
          person_name
        ),
        title = coalesce(
          nullif(trim(item ->> 'title'), ''),
          title
        ),
        linkedin_url = coalesce(
          linkedin_value,
          linkedin_url
        ),
        company_url = coalesce(
          nullif(trim(item ->> 'company_url'), ''),
          company_url
        ),
        email = coalesce(
          email_value,
          email
        ),
        country = coalesce(
          nullif(trim(item ->> 'country'), ''),
          country
        ),
        industry = coalesce(
          nullif(trim(item ->> 'industry'), ''),
          industry
        ),
        annual_revenue = coalesce(
          case
            when (item ->> 'annual_revenue') ~ '^[0-9]+$'
            then (item ->> 'annual_revenue')::bigint
            else null
          end,
          annual_revenue
        ),
        employee_count = coalesce(
          case
            when (item ->> 'employee_count') ~ '^[0-9]+$'
            then (item ->> 'employee_count')::integer
            else null
          end,
          employee_count
        ),
        business_model = coalesce(
          nullif(trim(item ->> 'business_model'), ''),
          business_model
        ),
        growth_stage = coalesce(
          nullif(trim(item ->> 'growth_stage'), ''),
          growth_stage
        ),
        buying_behavior = coalesce(
          nullif(trim(item ->> 'buying_behavior'), ''),
          buying_behavior
        ),
        raw_source_data = coalesce(
          raw_source_data,
          '{}'::jsonb
        ) || item,
        updated_at = now()
      where id = existing_lead.id
      returning * into stored_lead;

      updated_count := updated_count + 1;

    else
      insert into public.leads(
        import_id,
        created_by,
        company_name,
        person_name,
        title,
        linkedin_url,
        company_url,
        email,
        country,
        industry,
        annual_revenue,
        employee_count,
        business_model,
        growth_stage,
        buying_behavior,
        status,
        raw_source_data
      )
      values (
        import_record.id,
        null,
        company_value,
        nullif(trim(item ->> 'person_name'), ''),
        nullif(trim(item ->> 'title'), ''),
        linkedin_value,
        nullif(trim(item ->> 'company_url'), ''),
        email_value,
        nullif(trim(item ->> 'country'), ''),
        nullif(trim(item ->> 'industry'), ''),
        case
          when (item ->> 'annual_revenue') ~ '^[0-9]+$'
          then (item ->> 'annual_revenue')::bigint
          else null
        end,
        case
          when (item ->> 'employee_count') ~ '^[0-9]+$'
          then (item ->> 'employee_count')::integer
          else null
        end,
        nullif(trim(item ->> 'business_model'), ''),
        nullif(trim(item ->> 'growth_stage'), ''),
        nullif(trim(item ->> 'buying_behavior'), ''),
        'review',
        item
      )
      returning * into stored_lead;

      accepted_count := accepted_count + 1;
    end if;

    stored_ids := stored_ids || jsonb_build_array(
      jsonb_build_object(
        'lead_id',
        stored_lead.id,
        'linkedin_url',
        stored_lead.linkedin_url,
        'email',
        stored_lead.email,
        'vibe_business_id',
        item ->> 'vibe_business_id'
      )
    );
  end loop;

  update public.imports
  set
    status = 'completed',
    accepted_rows = accepted_count,
    rejected_rows = rejected_count,
    error_summary = jsonb_build_object(
      'errors',
      errors,
      'updated_existing',
      updated_count
    ),
    completed_at = now()
  where id = import_record.id;

  insert into public.audit_log(
    actor_id,
    action,
    entity_type,
    entity_id,
    details
  )
  values (
    null,
    'automatic_vibe_discovery_ingested',
    'import',
    import_record.id::text,
    jsonb_build_object(
      'inserted',
      accepted_count,
      'updated',
      updated_count,
      'rejected',
      rejected_count,
      'source',
      'vibe'
    )
  );

  return jsonb_build_object(
    'import_id',
    import_record.id,
    'inserted',
    accepted_count,
    'updated',
    updated_count,
    'rejected',
    rejected_count,
    'errors',
    errors,
    'leads',
    stored_ids
  );
end;
$$;

revoke all on function public.ingest_vibe_discovered_leads(jsonb)
from public;

revoke all on function public.ingest_vibe_discovered_leads(jsonb)
from anon;

revoke all on function public.ingest_vibe_discovered_leads(jsonb)
from authenticated;

grant execute on function public.ingest_vibe_discovered_leads(jsonb)
to service_role;

commit;
