begin;

create index if not exists processing_jobs_enrichment_claim_idx
  on public.processing_jobs (status, run_after, created_at)
  where job_type = 'enrich';

create or replace function public.claim_next_enrichment_job(worker_name text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare claimed public.processing_jobs;
begin
  if nullif(trim(worker_name), '') is null then raise exception 'Worker name is required'; end if;
  with next_job as (
    select id from public.processing_jobs
    where job_type = 'enrich' and status = 'queued' and run_after <= now() and attempts < max_attempts
    order by run_after, created_at for update skip locked limit 1
  )
  update public.processing_jobs job
  set status = 'running', attempts = attempts + 1, claimed_at = now(), claimed_by = worker_name, error_message = null
  from next_job where job.id = next_job.id returning job.* into claimed;
  if claimed.id is null then return null; end if;
  insert into public.audit_log(actor_id, action, entity_type, entity_id, details)
  values (null, 'enrichment_claimed', 'processing_job', claimed.id::text, jsonb_build_object('worker', worker_name, 'lead_id', claimed.lead_id));
  return to_jsonb(claimed);
end;
$$;

revoke all on function public.claim_next_enrichment_job(text) from public, anon, authenticated;
grant execute on function public.claim_next_enrichment_job(text) to service_role;
grant select on table public.evidence, public.processing_jobs to authenticated;

commit;
