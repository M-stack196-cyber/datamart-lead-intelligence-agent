begin;

-- Person-level identities replace the overly broad business-only uniqueness.
-- Existing records are retained. Lookup indexes tolerate pre-existing duplicates;
-- the serialized intake RPC below prevents adding further duplicates.
create schema if not exists private;

create or replace function private.vibe_normalized_name(value text)
returns text language sql immutable parallel safe set search_path = '' as $$
  select trim(regexp_replace(lower(coalesce(value, '')), '[^[:alnum:]_]+', ' ', 'g'));
$$;

create or replace function private.vibe_url_decode(value text)
returns text language plpgsql immutable parallel safe set search_path = '' as $$
declare
  result bytea := ''::bytea;
  position integer := 1;
  piece text;
begin
  while position <= length(value) loop
    piece := substr(value, position, 3);
    if piece ~ '^%[0-9a-fA-F]{2}$' then
      result := result || decode(substr(piece, 2, 2), 'hex');
      position := position + 3;
    else
      result := result || convert_to(substr(value, position, 1), 'UTF8');
      position := position + 1;
    end if;
  end loop;
  return convert_from(result, 'UTF8');
exception when character_not_in_repertoire then
  return value;
end;
$$;

create or replace function private.vibe_normalized_url(value text)
returns text language sql immutable parallel safe set search_path = '' as $$
  select rtrim(regexp_replace(regexp_replace(regexp_replace(
    lower(private.vibe_url_decode(trim(coalesce(value, '')))),
    '^https?://', ''), '^www\.', ''), '[?#].*$', ''), '/');
$$;

revoke all on function private.vibe_normalized_name(text),
  private.vibe_url_decode(text), private.vibe_normalized_url(text)
  from public, anon, authenticated;
grant usage on schema private to service_role;
grant execute on function private.vibe_normalized_name(text),
  private.vibe_url_decode(text), private.vibe_normalized_url(text) to service_role;

drop index if exists public.leads_vibe_business_id_unique;
create index if not exists leads_vibe_business_person_lookup
  on public.leads (lower(trim(vibe_business_id)), private.vibe_normalized_name(person_name));
create index if not exists leads_vibe_prospect_normalized_lookup
  on public.leads (lower(trim(vibe_prospect_id)));
create index if not exists leads_vibe_linkedin_normalized_lookup
  on public.leads (private.vibe_normalized_url(linkedin_url));
create index if not exists leads_vibe_website_person_lookup
  on public.leads (private.vibe_normalized_url(company_url), private.vibe_normalized_name(person_name));
create index if not exists leads_vibe_company_person_lookup
  on public.leads (private.vibe_normalized_name(company_name), private.vibe_normalized_name(person_name));

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
  company_url_value text;
  prospect_id_value text;
  business_id_value text;
  person_value text;
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

  -- Application runs above 100 are explicitly approved and split into safe,
  -- bounded batches before reaching this function.
  if jsonb_array_length(rows) > 100 then
    raise exception 'A single Vibe discovery batch is limited to 100 leads';
  end if;

  -- Discovery is a once-daily bounded operation. Serializing intake prevents
  -- crossed identity sets in concurrent manual/cron runs from deadlocking or
  -- inserting duplicates between lookup and insert.
  perform pg_advisory_xact_lock(hashtextextended(
    'datamart:vibe-discovery-intake', 0
  ));

  insert into public.imports(
    file_name, source, status, total_rows, created_by
  ) values (
    'automatic-vibe-discovery', 'vibe', 'processing',
    jsonb_array_length(rows), null
  ) returning * into import_record;

  for item in
    select value from jsonb_array_elements(rows)
  loop
    row_number := row_number + 1;
    existing_lead := null;
    stored_lead := null;

    person_value := nullif(trim(item ->> 'person_name'), '');
    linkedin_value := nullif(trim(item ->> 'linkedin_url'), '');
    email_value := nullif(lower(trim(item ->> 'email')), '');
    company_value := nullif(trim(item ->> 'company_name'), '');
    company_url_value := nullif(
      rtrim(trim(coalesce(item ->> 'company_url', item ->> 'company_website')), '/'),
      ''
    );
    prospect_id_value := nullif(trim(coalesce(
      item ->> 'vibe_prospect_id', item ->> 'prospect_id'
    )), '');
    business_id_value := nullif(trim(coalesce(
      item ->> 'vibe_business_id', item ->> 'business_id'
    )), '');

    if linkedin_value is null or company_url_value is null or company_value is null
       or person_value is null or nullif(trim(item ->> 'title'), '') is null then
      rejected_count := rejected_count + 1;
      errors := errors || jsonb_build_array(jsonb_build_object(
        'row', row_number, 'reason', 'Company, person, title, LinkedIn and company website are required'
      ));
      continue;
    end if;

    -- The transaction-level intake lock above serializes lookup and insert.
    -- Do not collapse different people at the same company, or shared mailboxes.
    select * into existing_lead from public.leads
    where (prospect_id_value is not null and
           lower(trim(vibe_prospect_id)) = lower(prospect_id_value))
       or private.vibe_normalized_url(linkedin_url) = private.vibe_normalized_url(linkedin_value)
       or (private.vibe_normalized_name(person_name) = private.vibe_normalized_name(person_value)
           and (
             (business_id_value is not null and lower(trim(vibe_business_id)) = lower(business_id_value))
             or private.vibe_normalized_url(company_url) = private.vibe_normalized_url(company_url_value)
             or private.vibe_normalized_name(company_name) = private.vibe_normalized_name(company_value)
           ))
    order by created_at, id
    limit 1;

    if existing_lead.id is not null then
      -- Report duplicates without changing their review state or producing new drafts.
      stored_lead := existing_lead;
      updated_count := updated_count + 1;
    else
      insert into public.leads(
        import_id, created_by, company_name, person_name, title,
        linkedin_url, company_url, email, country, industry,
        annual_revenue, employee_count, business_model, growth_stage,
        buying_behavior, status, raw_source_data, vibe_prospect_id,
        vibe_business_id, lead_source, source_captured_at
      ) values (
        import_record.id, null, coalesce(company_value, 'Unknown Company'),
        nullif(trim(item ->> 'person_name'), ''),
        nullif(trim(item ->> 'title'), ''), linkedin_value,
        company_url_value, email_value,
        nullif(trim(item ->> 'country'), ''),
        nullif(trim(item ->> 'industry'), ''),
        case when (item ->> 'annual_revenue') ~ '^[0-9]+$'
          then (item ->> 'annual_revenue')::bigint else null end,
        case when (item ->> 'employee_count') ~ '^[0-9]+$'
          then (item ->> 'employee_count')::integer else null end,
        nullif(trim(item ->> 'business_model'), ''),
        nullif(trim(item ->> 'growth_stage'), ''),
        nullif(trim(item ->> 'buying_behavior'), ''),
        'researching', item, prospect_id_value, business_id_value,
        'vibe', now()
      ) returning * into stored_lead;
      accepted_count := accepted_count + 1;
    end if;

    stored_ids := stored_ids || jsonb_build_array(jsonb_build_object(
      'lead_id', stored_lead.id,
      'duplicate', existing_lead.id is not null,
      'person_name', stored_lead.person_name,
      'company_name', stored_lead.company_name,
      'linkedin_url', stored_lead.linkedin_url,
      'email', stored_lead.email,
      'company_url', stored_lead.company_url,
      'vibe_prospect_id', stored_lead.vibe_prospect_id,
      'vibe_business_id', stored_lead.vibe_business_id
    ));
  end loop;

  update public.imports set
    status = 'completed', accepted_rows = accepted_count,
    rejected_rows = rejected_count,
    error_summary = jsonb_build_object(
      'errors', errors, 'duplicates', updated_count
    ), completed_at = now()
  where id = import_record.id;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (null, 'automatic_vibe_discovery_ingested', 'import',
    import_record.id::text, jsonb_build_object(
      'inserted', accepted_count, 'updated', 0, 'duplicates', updated_count,
      'rejected', rejected_count, 'source', 'vibe'
    ));

  return jsonb_build_object(
    'import_id', import_record.id, 'inserted', accepted_count,
    'updated', 0, 'duplicates', updated_count, 'rejected', rejected_count,
    'errors', errors, 'leads', stored_ids
  );
end;
$$;

revoke all on function public.ingest_vibe_discovered_leads(jsonb)
  from public, anon, authenticated;
grant execute on function public.ingest_vibe_discovered_leads(jsonb)
  to service_role;


commit;
