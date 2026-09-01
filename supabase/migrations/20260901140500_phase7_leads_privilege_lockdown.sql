begin;

-- Supabase's default authenticated grants can include non-RLS operations such
-- as TRUNCATE. Leads are read-only to the browser except through Phase 6/7 RPCs.
revoke all privileges on table public.leads from authenticated;
grant select on table public.leads to authenticated;

commit;
