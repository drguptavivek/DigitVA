alter table who_va_form_entries
  add column if not exists user_id text references who_va_users (user_id);

create index if not exists who_va_form_entries_user_id_idx on who_va_form_entries (user_id);

create table if not exists who_va_recorded_data (
  id bigserial primary key,
  entry_uid text not null references who_va_form_entries (uid) on delete cascade,
  user_id text references who_va_users (user_id),
  case_entry jsonb not null default '{}'::jsonb,
  who_va_prefill jsonb not null default '{}'::jsonb,
  submission jsonb not null default '{}'::jsonb,
  validation_issues jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists who_va_recorded_data_entry_uid_idx on who_va_recorded_data (entry_uid);
create index if not exists who_va_recorded_data_user_id_idx on who_va_recorded_data (user_id);
create index if not exists who_va_recorded_data_created_at_idx on who_va_recorded_data (created_at);
