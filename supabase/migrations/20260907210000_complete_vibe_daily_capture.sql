begin;

-- Provider identity and lifecycle metadata are additive. Archiving is a
-- reversible status change; this migration never deletes a lead.
alter table public.leads
  add column if not exists vibe_prospect_id text,
  add column if not exists vibe_business_id text,
  add column if not exists lead_source text,
  add column if not exists source_captured_at timestamptz,
  add column if not exists archived_at timestamptz,
  add column if not exists archive_reason text;

comment on column public.leads.archived_at is
  'Non-destructive retention marker. Leads remain stored when archived.';
comment on column public.leads.archive_reason is
  'Reason for a reversible archive decision after retention review, normally 6-12 months; never an instruction to delete.';

create unique index if not exists leads_vibe_prospect_id_unique
  on public.leads (lower(vibe_prospect_id))
  where vibe_prospect_id is not null;

create unique index if not exists leads_vibe_business_id_unique
  on public.leads (lower(vibe_business_id))
  where vibe_business_id is not null;

create index if not exists leads_company_url_lookup_idx
  on public.leads (lower(rtrim(company_url, '/')))
  where company_url is not null;

create index if not exists leads_source_captured_at_idx
  on public.leads (lead_source, source_captured_at desc)
  where lead_source is not null;

create index if not exists leads_archive_retention_idx
  on public.leads (archived_at)
  where archived_at is not null;

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

    if linkedin_value is null
       and email_value is null
       and company_url_value is null
       and prospect_id_value is null
       and business_id_value is null then
      rejected_count := rejected_count + 1;
      errors := errors || jsonb_build_array(jsonb_build_object(
        'row', row_number,
        'reason', 'A LinkedIn URL, email, company website, or Vibe ID is required'
      ));
      continue;
    end if;

    -- Fixed lock ordering prevents concurrent discovery runs from inserting
    -- the same provider identity between lookup and insert.
    if linkedin_value is not null then
      perform pg_advisory_xact_lock(hashtextextended(
        'linkedin:' || lower(rtrim(linkedin_value, '/')), 0
      ));
    end if;
    if email_value is not null then
      perform pg_advisory_xact_lock(hashtextextended('email:' || email_value, 0));
    end if;
    if company_url_value is not null then
      perform pg_advisory_xact_lock(hashtextextended(
        'company:' || lower(company_url_value), 0
      ));
    end if;
    if prospect_id_value is not null then
      perform pg_advisory_xact_lock(hashtextextended(
        'vibe-prospect:' || lower(prospect_id_value), 0
      ));
    end if;
    if business_id_value is not null then
      perform pg_advisory_xact_lock(hashtextextended(
        'vibe-business:' || lower(business_id_value), 0
      ));
    end if;

    if linkedin_value is not null then
      select * into existing_lead
      from public.leads
      where lower(rtrim(linkedin_url, '/')) = lower(rtrim(linkedin_value, '/'))
      order by created_at
      limit 1;
    end if;

    if existing_lead.id is null and email_value is not null then
      select * into existing_lead
      from public.leads
      where lower(email) = email_value
      order by created_at
      limit 1;
    end if;

    if existing_lead.id is null and company_url_value is not null then
      select * into existing_lead
      from public.leads
      where lower(rtrim(company_url, '/')) = lower(company_url_value)
      order by created_at
      limit 1;
    end if;

    if existing_lead.id is null and prospect_id_value is not null then
      select * into existing_lead
      from public.leads
      where lower(vibe_prospect_id) = lower(prospect_id_value)
      limit 1;
    end if;

    if existing_lead.id is null and business_id_value is not null then
      select * into existing_lead
      from public.leads
      where lower(vibe_business_id) = lower(business_id_value)
      limit 1;
    end if;

    if existing_lead.id is not null then
      update public.leads set
        company_name = case
          when nullif(trim(company_name), '') is null
               or company_name = 'Unknown Company'
          then coalesce(company_value, company_name, 'Unknown Company')
          else company_name
        end,
        person_name = coalesce(person_name, nullif(trim(item ->> 'person_name'), '')),
        title = coalesce(title, nullif(trim(item ->> 'title'), '')),
        linkedin_url = coalesce(linkedin_url, linkedin_value),
        company_url = coalesce(company_url, company_url_value),
        email = coalesce(email, email_value),
        country = coalesce(country, nullif(trim(item ->> 'country'), '')),
        industry = coalesce(industry, nullif(trim(item ->> 'industry'), '')),
        annual_revenue = coalesce(annual_revenue, case
          when (item ->> 'annual_revenue') ~ '^[0-9]+$'
          then (item ->> 'annual_revenue')::bigint else null end),
        employee_count = coalesce(employee_count, case
          when (item ->> 'employee_count') ~ '^[0-9]+$'
          then (item ->> 'employee_count')::integer else null end),
        business_model = coalesce(business_model, nullif(trim(item ->> 'business_model'), '')),
        growth_stage = coalesce(growth_stage, nullif(trim(item ->> 'growth_stage'), '')),
        buying_behavior = coalesce(buying_behavior, nullif(trim(item ->> 'buying_behavior'), '')),
        vibe_prospect_id = coalesce(vibe_prospect_id, prospect_id_value),
        vibe_business_id = coalesce(vibe_business_id, business_id_value),
        lead_source = coalesce(lead_source, 'vibe'),
        source_captured_at = coalesce(source_captured_at, now()),
        raw_source_data = coalesce(raw_source_data, '{}'::jsonb) || item,
        updated_at = now()
      where id = existing_lead.id
      returning * into stored_lead;
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
      'errors', errors, 'updated_existing', updated_count
    ), completed_at = now()
  where id = import_record.id;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (null, 'automatic_vibe_discovery_ingested', 'import',
    import_record.id::text, jsonb_build_object(
      'inserted', accepted_count, 'updated', updated_count,
      'rejected', rejected_count, 'source', 'vibe'
    ));

  return jsonb_build_object(
    'import_id', import_record.id, 'inserted', accepted_count,
    'updated', updated_count, 'rejected', rejected_count,
    'errors', errors, 'leads', stored_ids
  );
end;
$$;

revoke all on function public.ingest_vibe_discovered_leads(jsonb)
  from public, anon, authenticated;
grant execute on function public.ingest_vibe_discovered_leads(jsonb)
  to service_role;

create or replace function public.create_automatic_vibe_outreach_draft(
  target_lead_id uuid,
  draft_subject text,
  draft_body text,
  draft_evidence_ids uuid[]
)
returns public.outreach_drafts
language plpgsql
security definer
set search_path = ''
as $$
declare
  latest_score public.lead_scores;
  stored_draft public.outreach_drafts;
  evidence_count integer;
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception 'Service role required';
  end if;

  if nullif(trim(draft_body), '') is null or length(draft_body) > 4000 then
    raise exception 'A concise outreach body is required';
  end if;
  if cardinality(draft_evidence_ids) = 0 then
    raise exception 'Stored evidence is required for automatic outreach drafting';
  end if;

  select * into latest_score
  from public.lead_scores
  where lead_id = target_lead_id
  order by scored_at desc
  limit 1;

  if latest_score.id is null
     or latest_score.disposition not in ('Strong Fit', 'Good Fit')
     or jsonb_array_length(coalesce(latest_score.hard_stops, '[]'::jsonb)) > 0 then
    raise exception 'Only qualified leads without hard stops can receive a draft';
  end if;

  select count(*) into evidence_count
  from public.evidence
  where lead_id = target_lead_id and id = any(draft_evidence_ids);
  if evidence_count <> cardinality(draft_evidence_ids) then
    raise exception 'Every draft evidence item must belong to the lead';
  end if;

  insert into public.outreach_drafts(
    lead_id, sequence_step, channel, subject, body, status,
    evidence_ids, created_by, reviewed_by, reviewed_at
  ) values (
    target_lead_id, 1, 'email', nullif(trim(draft_subject), ''),
    draft_body, 'draft', draft_evidence_ids, null, null, null
  )
  on conflict (lead_id, channel, sequence_step) do update set
    subject = excluded.subject,
    body = excluded.body,
    evidence_ids = excluded.evidence_ids,
    reviewed_by = null,
    reviewed_at = null
  where public.outreach_drafts.status = 'draft'
  returning * into stored_draft;

  if stored_draft.id is null then
    raise exception 'An approved or rejected draft cannot be regenerated automatically';
  end if;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (null, 'automatic_vibe_outreach_draft_created', 'outreach_draft',
    stored_draft.id::text, jsonb_build_object(
      'lead_id', target_lead_id, 'evidence_ids', draft_evidence_ids,
      'delivery_attempted', false
    ));

  return stored_draft;
end;
$$;

revoke all on function public.create_automatic_vibe_outreach_draft(
  uuid, text, text, uuid[]
) from public, anon, authenticated;
grant execute on function public.create_automatic_vibe_outreach_draft(
  uuid, text, text, uuid[]
) to service_role;

commit;
