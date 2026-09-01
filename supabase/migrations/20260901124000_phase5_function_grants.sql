begin;

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

commit;
