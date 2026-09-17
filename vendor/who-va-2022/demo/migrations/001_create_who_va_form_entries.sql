create table if not exists who_va_form_entries (
  id bigserial primary key,
  uid text not null unique,
  case_entry jsonb not null default '{}'::jsonb,
  who_va_prefill jsonb not null default '{}'::jsonb,
  submission jsonb,
  validation_issues jsonb not null default '[]'::jsonb,
  status text not null default 'case-entry',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists who_va_form_entries_status_idx on who_va_form_entries (status);
create index if not exists who_va_form_entries_updated_at_idx on who_va_form_entries (updated_at);
