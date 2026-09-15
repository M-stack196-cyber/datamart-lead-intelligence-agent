alter table public.outreach_drafts
  add column if not exists sent_at timestamptz,
  add column if not exists manual_sent_at timestamptz,
  add column if not exists reply_wait_days integer,
  add column if not exists next_followup_decision_at timestamptz,
  add column if not exists followup_stopped_at timestamptz,
  add column if not exists followup_stop_reason text;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'outreach_drafts_reply_wait_days_positive'
      and conrelid = 'public.outreach_drafts'::regclass
  ) then
    alter table public.outreach_drafts
      add constraint outreach_drafts_reply_wait_days_positive
      check (reply_wait_days is null or reply_wait_days > 0)
      not valid;
  end if;
end $$;

alter table public.outreach_drafts
  validate constraint outreach_drafts_reply_wait_days_positive;

create index if not exists outreach_drafts_next_followup_decision_at_idx
  on public.outreach_drafts (next_followup_decision_at)
  where next_followup_decision_at is not null;
