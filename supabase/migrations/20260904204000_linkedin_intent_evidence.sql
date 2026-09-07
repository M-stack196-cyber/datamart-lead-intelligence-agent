begin;

alter table public.evidence
  drop constraint if exists evidence_evidence_type_check;

alter table public.evidence
  add constraint evidence_evidence_type_check
  check (
    evidence_type in (
      'linkedin_post',
      'linkedin_comment',
      'linkedin_activity',
      'company_page',
      'job_page',
      'news',
      'search_result',
      'other'
    )
  );

alter table public.evidence
  add column if not exists activity_at timestamptz,
  add column if not exists intent_signal text,
  add column if not exists intent_reason text,
  add column if not exists intent_score_delta integer
    check (
      intent_score_delta is null
      or intent_score_delta between 0 and 100
    );

create index if not exists evidence_activity_at_idx
  on public.evidence(activity_at desc);

create index if not exists evidence_linkedin_type_idx
  on public.evidence(evidence_type, activity_at desc)
  where evidence_type in (
    'linkedin_post',
    'linkedin_comment',
    'linkedin_activity'
  );

commit;

begin;

create or replace function public.store_linkedin_intent_evidence(
  target_lead_id uuid,
  evidence_items jsonb
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  actor_id uuid;
  evidence_item jsonb;
  stored_count integer := 0;
  item_type text;
  item_url text;
  item_title text;
begin
  actor_id := auth.uid();

  if actor_id is null then
    raise exception 'Authentication required';
  end if;

  if not exists (
    select 1
    from public.profiles
    where id = actor_id
      and role in ('admin', 'manager', 'sales')
  ) then
    raise exception 'Authorized company role required';
  end if;

  if not exists (
    select 1
    from public.leads
    where id = target_lead_id
  ) then
    raise exception 'Lead not found';
  end if;

  if not public.can_access_lead(target_lead_id) then
    raise exception 'Lead access required';
  end if;

  if jsonb_typeof(evidence_items) <> 'array' then
    raise exception 'evidence_items must be an array';
  end if;

  for evidence_item in
    select value
    from jsonb_array_elements(evidence_items)
  loop
    item_type := trim(
      coalesce(
        evidence_item ->> 'evidence_type',
        ''
      )
    );

    item_url := trim(
      coalesce(
        evidence_item ->> 'source_url',
        ''
      )
    );

    item_title := trim(
      coalesce(
        evidence_item ->> 'title',
        ''
      )
    );

    if item_type not in (
      'linkedin_post',
      'linkedin_comment',
      'linkedin_activity'
    ) then
      continue;
    end if;

    if item_url = '' or item_title = '' then
      continue;
    end if;

    if exists (
      select 1
      from public.evidence
      where lead_id = target_lead_id
        and evidence_type = item_type
        and lower(source_url) = lower(item_url)
    ) then
      continue;
    end if;
    insert into public.evidence (
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
      item_type,
      item_title,
      item_url,
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
      actor_id
    );

    stored_count := stored_count + 1;
  end loop;

  return stored_count;
end;
$$;

revoke all on function public.store_linkedin_intent_evidence(
  uuid,
  jsonb
) from public;

revoke all on function public.store_linkedin_intent_evidence(
  uuid,
  jsonb
) from anon;

grant execute on function public.store_linkedin_intent_evidence(
  uuid,
  jsonb
) to authenticated;

commit;

begin;

create or replace function public.store_worker_linkedin_intent_evidence(
  target_lead_id uuid,
  evidence_items jsonb
)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  evidence_item jsonb;
  item_type text;
  item_url text;
  item_title text;
  stored_count integer := 0;
begin
  if coalesce(current_setting('request.jwt.claim.role', true), '') <> 'service_role' then
    raise exception 'Service role required';
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
    item_type := trim(
      coalesce(
        evidence_item ->> 'evidence_type',
        ''
      )
    );

    item_url := trim(
      coalesce(
        evidence_item ->> 'source_url',
        ''
      )
    );

    item_title := trim(
      coalesce(
        evidence_item ->> 'title',
        ''
      )
    );

    if item_type not in (
      'linkedin_post',
      'linkedin_comment',
      'linkedin_activity'
    ) then
      continue;
    end if;

    if item_url = '' or item_title = '' then
      continue;
    end if;

    if exists (
      select 1
      from public.evidence
      where lead_id = target_lead_id
        and evidence_type = item_type
        and lower(source_url) = lower(item_url)
    ) then
      continue;
    end if;

    insert into public.evidence (
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
      metadata
    )
    values (
      target_lead_id,
      item_type,
      item_title,
      item_url,
      nullif(
        trim(evidence_item ->> 'publisher'),
        ''
      ),
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
      nullif(
        trim(evidence_item ->> 'excerpt'),
        ''
      ),
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
      nullif(
        trim(evidence_item ->> 'intent_signal'),
        ''
      ),
      nullif(
        trim(evidence_item ->> 'intent_reason'),
        ''
      ),
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
      )
    )
    on conflict do nothing;

    stored_count := stored_count + 1;
  end loop;

  return stored_count;
end;
$$;

revoke all on function public.store_worker_linkedin_intent_evidence(
  uuid,
  jsonb
) from public;

revoke all on function public.store_worker_linkedin_intent_evidence(
  uuid,
  jsonb
) from anon;

revoke all on function public.store_worker_linkedin_intent_evidence(
  uuid,
  jsonb
) from authenticated;

grant execute on function public.store_worker_linkedin_intent_evidence(
  uuid,
  jsonb
) to service_role;

commit;
