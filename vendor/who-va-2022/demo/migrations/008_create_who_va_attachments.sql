create table if not exists who_va_attachments (
  id text primary key,
  original_name text,
  stored_name text not null,
  mime_type text not null,
  size_bytes integer not null,
  storage_path text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists who_va_attachments_updated_at_idx on who_va_attachments (updated_at);