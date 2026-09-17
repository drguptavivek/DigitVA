create table if not exists who_va_users (
  user_id text primary key,
  name text not null,
  email text not null unique,
  role text not null default 'data-entry',
  partner_site text not null,
  site_assigned text not null,
  password_hash text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists who_va_users_partner_site_idx on who_va_users (partner_site);
create index if not exists who_va_users_site_assigned_idx on who_va_users (site_assigned);
create index if not exists who_va_users_role_idx on who_va_users (role);
