begin;

alter type public.outbound_lifecycle_status
  add value if not exists 'sending';

create index if not exists lead_outreach_due_sequence_idx
  on public.lead_outreach(next_run_at)
  where status = 'scheduled';

create index if not exists lead_outreach_sequence_status_idx
  on public.lead_outreach(sequence_id, status, current_step_number);

create index if not exists outreach_messages_sequence_step_idx
  on public.outreach_messages(
    lead_outreach_id,
    step_number,
    direction
  );

commit;
