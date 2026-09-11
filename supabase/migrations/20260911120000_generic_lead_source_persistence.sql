begin;

alter table public.leads
  add column if not exists source_id text,
  add column if not exists phone text;

create index if not exists leads_source_identity_lookup_idx
  on public.leads (lead_source, lower(source_id))
  where lead_source is not null and source_id is not null;

create index if not exists leads_generic_website_person_lookup_idx
  on public.leads (lower(rtrim(company_url, '/')), lower(person_name))
  where company_url is not null and person_name is not null;

commit;
