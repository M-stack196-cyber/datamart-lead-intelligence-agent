begin;

alter table public.leads
  add column if not exists has_funding_or_revenue boolean,
  add column if not exists has_defined_software_need boolean,
  add column if not exists has_technical_stakeholder boolean,
  add column if not exists accepts_distributed_delivery boolean;

alter table public.lead_scores
  add column if not exists source_job_id uuid references public.processing_jobs(id) on delete set null,
  add column if not exists review_reasons jsonb not null default '[]'::jsonb,
  add column if not exists intent_score integer not null default 0 check (intent_score between 0 and 100),
  add column if not exists intent_level text not null default 'low' check (intent_level in ('low', 'medium', 'high')),
  add column if not exists intent_reasons jsonb not null default '[]'::jsonb;

alter table public.lead_scores
  drop constraint if exists lead_scores_source_job_id_key;
alter table public.lead_scores
  add constraint lead_scores_source_job_id_key unique (source_job_id);

create or replace function public.complete_enrichment_intelligence_job(
  target_job_id uuid,
  provider_fields jsonb,
  provider_evidence jsonb,
  score_result jsonb,
  intent_result jsonb,
  provider_result jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  claimed_job public.processing_jobs;
  active_icp public.icp_versions;
  stored_evidence_id uuid;
  stored_evidence_ids uuid[] := '{}';
  evidence_item jsonb;
  computed_status public.lead_status;
  completed_result jsonb;
begin
  select * into claimed_job
  from public.processing_jobs
  where id = target_job_id
  for update;

  if claimed_job.id is null or claimed_job.job_type <> 'enrich' then
    raise exception 'Enrichment job not found';
  end if;
  if claimed_job.status = 'completed' then
    return claimed_job.result;
  end if;
  if claimed_job.status <> 'running' then
    raise exception 'Enrichment job must be claimed before completion';
  end if;
  if jsonb_typeof(coalesce(provider_fields, '{}'::jsonb)) <> 'object'
     or jsonb_typeof(coalesce(provider_evidence, '[]'::jsonb)) <> 'array'
     or jsonb_typeof(coalesce(score_result, '{}'::jsonb)) <> 'object'
     or jsonb_typeof(coalesce(intent_result, '{}'::jsonb)) <> 'object' then
    raise exception 'Invalid enrichment intelligence payload';
  end if;

  select * into active_icp
  from public.icp_versions
  where external_id = score_result ->> 'icp_id';
  if active_icp.id is null then
    raise exception 'Scoring ICP version not found';
  end if;

  -- Only nonblank, explicitly supported provider fields can replace stored lead
  -- values. Blank provider values can never erase human-entered information.
  update public.leads
  set company_name = coalesce(nullif(trim(provider_fields ->> 'company_name'), ''), company_name),
      person_name = coalesce(nullif(trim(provider_fields ->> 'person_name'), ''), person_name),
      title = coalesce(nullif(trim(provider_fields ->> 'title'), ''), title),
      country = coalesce(nullif(trim(provider_fields ->> 'country'), ''), country),
      industry = coalesce(nullif(trim(provider_fields ->> 'industry'), ''), industry),
      email = coalesce(nullif(lower(trim(provider_fields ->> 'email')), ''), email)
  where id = claimed_job.lead_id;

  for evidence_item in select value from jsonb_array_elements(provider_evidence)
  loop
    if nullif(trim(evidence_item ->> 'title'), '') is null
       or nullif(trim(evidence_item ->> 'source_url'), '') is null
       or coalesce(evidence_item ->> 'evidence_type', 'other') not in (
         'linkedin_post', 'company_page', 'job_page', 'news', 'search_result', 'other'
       ) then
      continue;
    end if;

    select id into stored_evidence_id
    from public.evidence
    where lead_id = claimed_job.lead_id
      and evidence_type = coalesce(evidence_item ->> 'evidence_type', 'other')
      and lower(source_url) = lower(evidence_item ->> 'source_url')
    order by captured_at
    limit 1;

    if stored_evidence_id is null then
      insert into public.evidence (
        lead_id, evidence_type, title, source_url, publisher, excerpt,
        supports_fields, metadata, created_by
      ) values (
        claimed_job.lead_id,
        coalesce(evidence_item ->> 'evidence_type', 'other'),
        trim(evidence_item ->> 'title'),
        trim(evidence_item ->> 'source_url'),
        nullif(trim(evidence_item ->> 'publisher'), ''),
        nullif(trim(evidence_item ->> 'excerpt'), ''),
        coalesce(
          array(select jsonb_array_elements_text(coalesce(evidence_item -> 'supports_fields', '[]'::jsonb))),
          '{}'
        ),
        coalesce(evidence_item -> 'metadata', '{}'::jsonb),
        claimed_job.created_by
      ) returning id into stored_evidence_id;
    end if;
    stored_evidence_ids := array_append(stored_evidence_ids, stored_evidence_id);
    stored_evidence_id := null;
  end loop;

  if jsonb_array_length(coalesce(score_result -> 'hard_stops', '[]'::jsonb)) > 0 then
    computed_status := 'disqualified';
  elsif score_result ->> 'disposition' = 'Not Qualified'
        and coalesce(intent_result ->> 'level', 'low') = 'low' then
    computed_status := 'nurture';
  else
    computed_status := 'review';
  end if;

  insert into public.lead_scores (
    lead_id, icp_version_id, source_job_id, score, disposition, tier,
    persona, hard_stops, review_reasons, evaluations, evidence_ids,
    intent_score, intent_level, intent_reasons, scored_by
  ) values (
    claimed_job.lead_id,
    active_icp.id,
    claimed_job.id,
    (score_result ->> 'score')::integer,
    score_result ->> 'disposition',
    score_result ->> 'tier',
    nullif(score_result ->> 'persona', ''),
    coalesce(score_result -> 'hard_stops', '[]'::jsonb),
    coalesce(score_result -> 'review_reasons', '[]'::jsonb),
    coalesce(score_result -> 'evaluations', '[]'::jsonb),
    stored_evidence_ids,
    (intent_result ->> 'score')::integer,
    intent_result ->> 'level',
    coalesce(intent_result -> 'reasons', '[]'::jsonb),
    null
  )
  on conflict (source_job_id) do update
  set icp_version_id = excluded.icp_version_id,
      score = excluded.score,
      disposition = excluded.disposition,
      tier = excluded.tier,
      persona = excluded.persona,
      hard_stops = excluded.hard_stops,
      review_reasons = excluded.review_reasons,
      evaluations = excluded.evaluations,
      evidence_ids = excluded.evidence_ids,
      intent_score = excluded.intent_score,
      intent_level = excluded.intent_level,
      intent_reasons = excluded.intent_reasons,
      scored_at = now();

  update public.leads
  set status = computed_status,
      sales_approved_at = case when computed_status = 'disqualified' then null else sales_approved_at end,
      sales_approved_by = case when computed_status = 'disqualified' then null else sales_approved_by end
  where id = claimed_job.lead_id;

  completed_result := coalesce(provider_result, '{}'::jsonb) || jsonb_build_object(
    'icp_score', (score_result ->> 'score')::integer,
    'disposition', score_result ->> 'disposition',
    'hard_stops', coalesce(score_result -> 'hard_stops', '[]'::jsonb),
    'review_reasons', coalesce(score_result -> 'review_reasons', '[]'::jsonb),
    'intent_score', (intent_result ->> 'score')::integer,
    'intent_level', intent_result ->> 'level',
    'intent_reasons', coalesce(intent_result -> 'reasons', '[]'::jsonb),
    'evidence_count', cardinality(stored_evidence_ids),
    'lead_status', computed_status,
    'icp_external_id', active_icp.external_id,
    'icp_version', active_icp.version
  );

  update public.processing_jobs
  set status = 'completed',
      completed_at = now(),
      claimed_at = null,
      claimed_by = null,
      result = completed_result,
      error_message = null
  where id = claimed_job.id;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    null,
    'enrichment_intelligence_completed',
    'processing_job',
    claimed_job.id::text,
    jsonb_build_object(
      'lead_id', claimed_job.lead_id,
      'status', computed_status,
      'score', (score_result ->> 'score')::integer,
      'disposition', score_result ->> 'disposition',
      'intent_level', intent_result ->> 'level'
    )
  );

  return completed_result;
end;
$$;

revoke all on function public.complete_enrichment_intelligence_job(
  uuid, jsonb, jsonb, jsonb, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.complete_enrichment_intelligence_job(
  uuid, jsonb, jsonb, jsonb, jsonb, jsonb
) to service_role;

commit;
