begin;

create table if not exists public.sender_account_oauth_tokens (
  id uuid primary key default gen_random_uuid(),
  sender_account_id uuid not null references public.sender_accounts(id) on delete cascade,
  provider text not null default 'gmail',
  encrypted_access_token text,
  encrypted_refresh_token text,
  token_type text,
  scope text,
  expires_at timestamptz,
  google_email text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint sender_account_oauth_tokens_provider_check check (provider in ('gmail'))
);

create unique index if not exists sender_account_oauth_tokens_sender_provider_idx
  on public.sender_account_oauth_tokens (sender_account_id, provider);

drop trigger if exists sender_account_oauth_tokens_set_updated_at on public.sender_account_oauth_tokens;
create trigger sender_account_oauth_tokens_set_updated_at
before update on public.sender_account_oauth_tokens
for each row execute function public.set_updated_at();

alter table public.sender_account_oauth_tokens enable row level security;

drop policy if exists sender_account_oauth_tokens_no_browser_access on public.sender_account_oauth_tokens;
create policy sender_account_oauth_tokens_no_browser_access on public.sender_account_oauth_tokens
for all to authenticated
using (false)
with check (false);

revoke all on table public.sender_account_oauth_tokens from anon, authenticated;

commit;
