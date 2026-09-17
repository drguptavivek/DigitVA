create table if not exists who_va_user_sessions (
  session_id text primary key,
  user_id text not null references who_va_users(user_id) on delete cascade,
  device_id text,
  access_token_hash text not null unique,
  refresh_token_hash text not null unique,
  access_expires_at timestamptz not null,
  refresh_expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists who_va_user_sessions_user_id_idx on who_va_user_sessions (user_id);
create index if not exists who_va_user_sessions_access_token_hash_idx
  on who_va_user_sessions (access_token_hash);
create index if not exists who_va_user_sessions_refresh_token_hash_idx
  on who_va_user_sessions (refresh_token_hash);
