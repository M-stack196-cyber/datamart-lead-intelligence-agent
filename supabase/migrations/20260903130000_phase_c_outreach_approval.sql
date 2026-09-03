begin;

alter table public.outreach_messages
  add column if not exists approved_by uuid references public.profiles(id);

create index if not exists outreach_messages_approved_by_idx
  on public.outreach_messages(approved_by)
  where approved_by is not null;

commit;
