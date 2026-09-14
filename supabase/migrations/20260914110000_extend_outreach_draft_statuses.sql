alter type public.outreach_status add value if not exists 'needs_edit';
alter type public.outreach_status add value if not exists 'sent';
alter type public.outreach_status add value if not exists 'manual_sent';
alter type public.outreach_status add value if not exists 'system_sent';
alter type public.outreach_status add value if not exists 'archived';
alter type public.outreach_status add value if not exists 'cancelled';
