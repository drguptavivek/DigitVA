create table if not exists who_va_drafts (
  id text primary key,
  user_id text,
  draft jsonb not null,
  instrument_id text not null,
  instrument_version text not null,
  current_section text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists who_va_drafts_updated_at_idx on who_va_drafts (updated_at);
create index if not exists who_va_drafts_user_id_idx on who_va_drafts (user_id);
