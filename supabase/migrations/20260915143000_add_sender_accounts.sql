begin;

create table if not exists public.sender_accounts (
  id uuid primary key default gen_random_uuid(),
  display_name text not null,
  email_address text not null,
  provider text not null check (provider in ('gmail_oauth', 'smtp', 'manual_only')),
  status text not null default 'not_connected' check (status in ('not_connected', 'connected', 'disabled', 'error')),
  is_active boolean not null default true,
  daily_send_limit integer,
  sent_today integer not null default 0,
  last_sent_at timestamptz,
  reply_tracking_enabled boolean not null default false,
  provider_config jsonb not null default '{}'::jsonb,
  created_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint sender_accounts_daily_send_limit_positive check (daily_send_limit is null or daily_send_limit > 0),
  constraint sender_accounts_sent_today_nonnegative check (sent_today >= 0),
  constraint sender_accounts_provider_config_no_secret_keys check (
    not (
      provider_config ?| array[
        'password',
        'token',
        'access_token',
        'refresh_token',
        'client_secret',
        'smtp_password',
        'app_password',
        'secret'
      ]
    )
  )
);

create unique index if not exists sender_accounts_email_unique_idx
  on public.sender_accounts (lower(email_address));

create index if not exists sender_accounts_status_active_idx
  on public.sender_accounts (status, is_active);

create index if not exists sender_accounts_provider_idx
  on public.sender_accounts (provider);

drop trigger if exists sender_accounts_set_updated_at on public.sender_accounts;
create trigger sender_accounts_set_updated_at
before update on public.sender_accounts
for each row execute function public.set_updated_at();

alter table public.sender_accounts enable row level security;

drop policy if exists sender_accounts_select on public.sender_accounts;
create policy sender_accounts_select on public.sender_accounts
for select to authenticated
using (
  public.is_manager_or_admin()
  or (is_active = true and status in ('connected', 'not_connected'))
);

drop policy if exists sender_accounts_insert on public.sender_accounts;
create policy sender_accounts_insert on public.sender_accounts
for insert to authenticated
with check (public.is_manager_or_admin());

drop policy if exists sender_accounts_update on public.sender_accounts;
create policy sender_accounts_update on public.sender_accounts
for update to authenticated
using (public.is_manager_or_admin())
with check (public.is_manager_or_admin());

revoke all on table public.sender_accounts from anon, authenticated;
grant select on table public.sender_accounts to authenticated;

alter table public.outreach_drafts
  add column if not exists sender_account_id uuid references public.sender_accounts(id),
  add column if not exists sent_from_email text;

create index if not exists outreach_drafts_sender_account_idx
  on public.outreach_drafts (sender_account_id)
  where sender_account_id is not null;

do $$
begin
  if to_regclass('public.email_delivery_attempts') is not null then
    alter table public.email_delivery_attempts
      add column if not exists sender_account_id uuid references public.sender_accounts(id),
      add column if not exists sent_from_email text;

    create index if not exists email_delivery_attempts_sender_account_idx
      on public.email_delivery_attempts (sender_account_id)
      where sender_account_id is not null;
  end if;
end $$;

commit;
