begin;

-- Supabase may grant functions directly to API roles. Keep anonymous users away
-- from every SECURITY DEFINER helper, including trigger-only functions.
revoke all on function public.current_app_role() from public, anon;
revoke all on function public.is_manager_or_admin() from public, anon;
revoke all on function public.can_access_lead(uuid) from public, anon;
revoke all on function public.set_user_role(uuid, public.app_role) from public, anon;
revoke all on function public.publish_icp_version(uuid) from public, anon;
revoke all on function public.handle_new_user() from public, anon, authenticated;
revoke all on function public.set_updated_at() from public, anon, authenticated;
grant execute on function public.current_app_role() to authenticated;
grant execute on function public.is_manager_or_admin() to authenticated;
grant execute on function public.can_access_lead(uuid) to authenticated;
grant execute on function public.set_user_role(uuid, public.app_role) to authenticated;
grant execute on function public.publish_icp_version(uuid) to authenticated;

-- Cover relationship columns used by joins, cleanup, audit, and assignment views.
create index audit_log_actor_id_idx on public.audit_log(actor_id);
create index evidence_created_by_idx on public.evidence(created_by);
create index icp_versions_created_by_idx on public.icp_versions(created_by);
create index icp_versions_approved_by_idx on public.icp_versions(approved_by);
create index imports_created_by_idx on public.imports(created_by);
create index leads_import_id_idx on public.leads(import_id);
create index leads_created_by_idx on public.leads(created_by);
create index lead_scores_icp_version_id_idx on public.lead_scores(icp_version_id);
create index lead_scores_scored_by_idx on public.lead_scores(scored_by);
create index processing_jobs_lead_id_idx on public.processing_jobs(lead_id);
create index processing_jobs_created_by_idx on public.processing_jobs(created_by);
create index outreach_drafts_created_by_idx on public.outreach_drafts(created_by);
create index outreach_drafts_reviewed_by_idx on public.outreach_drafts(reviewed_by);

commit;
