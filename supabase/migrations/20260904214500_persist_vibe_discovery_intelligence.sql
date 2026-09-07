begin;

create or replace function public.persist_vibe_discovery_intelligence(
  target_lead_id uuid,
  score_result jsonb,
  intent_result jsonb,
  evidence_items jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  active_icp public.icp_versions;
  evidence_item jsonb;
  stored_evidence_id uuid;
  stored_evidence_ids uuid[] := '{}';
  computed_status public.lead_status := 'review';
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception 'Service role required';
  end if;

  select *
  into active_icp
  from public.icp_versions
  where status = 'active'
  order by version desc
  limit 1;

  if active_icp.id is null then
    raise exception 'No active ICP version found';
  end if;

  if not exists (
    select 1
    from public.leads
    where id = target_lead_id
  ) then
    raise exception 'Lead not found';
  end if;

  if jsonb_typeof(evidence_items) <> 'array' then
    raise exception 'evidence_items must be an array';
  end if;

  for evidence_item in
    select value
    from jsonb_array_elements(evidence_items)
  loop
    if nullif(trim(evidence_item ->> 'title'), '') is null
       or nullif(trim(evidence_item ->> 'source_url'), '') is null then
      continue;
    end if;

    stored_evidence_id := null;

    select id
    into stored_evidence_id
    from public.evidence
    where lead_id = target_lead_id
      and evidence_type = coalesce(
        nullif(trim(evidence_item ->> 'evidence_type'), ''),
        'other'
      )
      and lower(source_url) = lower(
        trim(evidence_item ->> 'source_url')
      )
    order by captured_at
    limit 1;

    if stored_evidence_id is null then
      insert into public.evidence(
        lead_id,
        evidence_type,
        title,
        source_url,
        publisher,
        published_at,
        activity_at,
        captured_at,
        excerpt,
        supports_fields,
        intent_signal,
        intent_reason,
        intent_score_delta,
        metadata,
        created_by
      )
      values (
        target_lead_id,
        coalesce(
          nullif(trim(evidence_item ->> 'evidence_type'), ''),
          'other'
        ),
        trim(evidence_item ->> 'title'),
        trim(evidence_item ->> 'source_url'),
        nullif(trim(evidence_item ->> 'publisher'), ''),
        case
          when nullif(
            evidence_item ->> 'published_at',
            ''
          ) is not null
          then (
            evidence_item ->> 'published_at'
          )::timestamptz
          else null
        end,
        case
          when nullif(
            evidence_item ->> 'activity_at',
            ''
          ) is not null
          then (
            evidence_item ->> 'activity_at'
          )::timestamptz
          else null
        end,
        now(),
        nullif(trim(evidence_item ->> 'excerpt'), ''),
        coalesce(
          array(
            select jsonb_array_elements_text(
              coalesce(
                evidence_item -> 'supports_fields',
                '[]'::jsonb
              )
            )
          ),
          '{}'
        ),
        nullif(trim(evidence_item ->> 'intent_signal'), ''),
        nullif(trim(evidence_item ->> 'intent_reason'), ''),
        case
          when (
            evidence_item ->> 'intent_score_delta'
          ) ~ '^[0-9]+$'
          then least(
            100,
            greatest(
              0,
              (
                evidence_item
                ->> 'intent_score_delta'
              )::integer
            )
          )
          else null
        end,
        coalesce(
          evidence_item -> 'metadata',
          '{}'::jsonb
        ),
        null
      )
      returning id
      into stored_evidence_id;
    end if;

    stored_evidence_ids := array_append(
      stored_evidence_ids,
      stored_evidence_id
    );
  end loop;

  if jsonb_array_length(
    coalesce(
      score_result -> 'hard_stops',
      '[]'::jsonb
    )
  ) > 0 then
    computed_status := 'disqualified';

  elsif score_result ->> 'disposition' = 'Not Qualified'
        and coalesce(
          intent_result ->> 'level',
          'low'
        ) = 'low' then
    computed_status := 'nurture';

  else
    computed_status := 'review';
  end if;

  insert into public.lead_scores(
    lead_id,
    icp_version_id,
    source_job_id,
    score,
    disposition,
    tier,
    persona,
    hard_stops,
    review_reasons,
    evaluations,
    evidence_ids,
    intent_score,
    intent_level,
    intent_reasons,
    scored_by
  )
  values (
    target_lead_id,
    active_icp.id,
    null,
    (score_result ->> 'score')::integer,
    score_result ->> 'disposition',
    score_result ->> 'tier',
    nullif(score_result ->> 'persona', ''),
    coalesce(
      score_result -> 'hard_stops',
      '[]'::jsonb
    ),
    coalesce(
      score_result -> 'review_reasons',
      '[]'::jsonb
    ),
    coalesce(
      score_result -> 'evaluations',
      '[]'::jsonb
    ),
    stored_evidence_ids,
    (intent_result ->> 'score')::integer,
    intent_result ->> 'level',
    coalesce(
      intent_result -> 'reasons',
      '[]'::jsonb
    ),
    null
  );

  update public.leads
  set
    status = computed_status,
    updated_at = now(),
    sales_approved_at = case
      when computed_status = 'disqualified'
      then null
      else sales_approved_at
    end,
    sales_approved_by = case
      when computed_status = 'disqualified'
      then null
      else sales_approved_by
    end
  where id = target_lead_id;

  insert into public.audit_log(
    actor_id,
    action,
    entity_type,
    entity_id,
    details
  )
  values (
    null,
    'automatic_vibe_intelligence_persisted',
    'lead',
    target_lead_id::text,
    jsonb_build_object(
      'score',
      (score_result ->> 'score')::integer,
      'disposition',
      score_result ->> 'disposition',
      'intent_score',
      (intent_result ->> 'score')::integer,
      'intent_level',
      intent_result ->> 'level',
      'evidence_count',
      cardinality(stored_evidence_ids)
    )
  );

  return jsonb_build_object(
    'lead_id',
    target_lead_id,
    'status',
    computed_status,
    'evidence_count',
    cardinality(stored_evidence_ids),
    'evidence_ids',
    to_jsonb(stored_evidence_ids),
    'icp_version',
    active_icp.version
  );
end;
$$;

revoke all on function public.persist_vibe_discovery_intelligence(
  uuid,
  jsonb,
  jsonb,
  jsonb
) from public;

revoke all on function public.persist_vibe_discovery_intelligence(
  uuid,
  jsonb,
  jsonb,
  jsonb
) from anon;

revoke all on function public.persist_vibe_discovery_intelligence(
  uuid,
  jsonb,
  jsonb,
  jsonb
) from authenticated;

grant execute on function public.persist_vibe_discovery_intelligence(
  uuid,
  jsonb,
  jsonb,
  jsonb
) to service_role;

commit;
