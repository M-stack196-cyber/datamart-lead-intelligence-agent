begin;

alter table public.lead_scores
  drop constraint if exists lead_scores_disposition_check;
alter table public.lead_scores
  add constraint lead_scores_disposition_check
  check (disposition in (
    'Strong Fit',
    'Good Fit',
    'Review',
    'Opportunistic / Manual Review',
    'Not Qualified',
    'Disqualified'
  ));

-- Preserve the historical v1 definition and publish a corrected v2. Country
-- outside USA/UAE becomes an explicit review rule, never a hard stop.
do $$
begin
  if not exists (
    select 1 from public.icp_versions where external_id = 'datamart-icp-v1'
  ) then
    raise exception 'datamart-icp-v1 must be seeded before applying the geography correction';
  end if;
end;
$$;

update public.icp_versions
set status = 'archived',
    definition = jsonb_set(definition, '{status}', '"archived"'::jsonb, true),
    archived_at = now()
where status = 'active';

with source as (
  select *
  from public.icp_versions
  where external_id = 'datamart-icp-v1'
), prepared as (
  select
    s.definition || jsonb_build_object(
      'id', 'datamart-icp-v2',
      'version', 2,
      'status', 'active',
      'effective_date', '2026-09-03',
      'source', s.source || '; confirmed geography rule 2026-09-03',
      'hard_stops', coalesce(
        (
          select jsonb_agg(rule order by ordinal)
          from jsonb_array_elements(s.definition -> 'hard_stops') with ordinality as rules(rule, ordinal)
          where rule ->> 'key' <> 'outside_geography'
        ),
        '[]'::jsonb
      ),
      'manual_review_rules', jsonb_build_array(jsonb_build_object(
        'key', 'outside_geography',
        'label', 'Opportunistic geography',
        'description', 'Headquarters outside USA/UAE receives no geography points and requires manual review; it is not a hard disqualification.'
      ))
    ) as definition,
    s.source || '; confirmed geography rule 2026-09-03' as source,
    s.created_by,
    s.approved_by
  from source as s
)
insert into public.icp_versions (
  external_id, name, version, status, definition, source, effective_date,
  created_by, approved_by, published_at, archived_at
)
select
  'datamart-icp-v2', 'Datamart Core ICP', 2, 'active', definition, source,
  date '2026-09-03', created_by, approved_by, now(), null
from prepared
on conflict (external_id) do update
set status = excluded.status,
    definition = excluded.definition,
    source = excluded.source,
    effective_date = excluded.effective_date,
    approved_by = excluded.approved_by,
    published_at = excluded.published_at,
    archived_at = null;

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

  select * into latest_score
  from public.lead_scores
  where lead_id = target_id
  order by scored_at desc
  limit 1;
  if latest_score.id is null then
    raise exception 'A scored lead is required before sales approval';
  end if;
  if coalesce(jsonb_array_length(latest_score.hard_stops), 0) > 0
     or latest_score.disposition not in (
       'Strong Fit', 'Good Fit', 'Opportunistic / Manual Review'
     ) then
    raise exception 'Only an eligible scored lead without hard stops can be approved';
  end if;

  update public.leads
  set sales_approved_at = now(),
      sales_approved_by = actor_id,
      status = 'qualified'
  where id = target_id and status <> 'disqualified'
  returning * into updated_lead;
  if updated_lead.id is null then
    raise exception 'Lead not found or disqualified';
  end if;

  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (
    actor_id,
    'lead_approved_for_sales',
    'lead',
    target_id::text,
    jsonb_build_object(
      'score', latest_score.score,
      'disposition', latest_score.disposition
    )
  );
  return updated_lead;
end;
$$;

revoke all on function public.approve_lead_for_sales(uuid) from public, anon;
grant execute on function public.approve_lead_for_sales(uuid) to authenticated;

commit;
