alter table who_va_recorded_data
  add column if not exists snapshot_type text not null default 'completed';

create index if not exists who_va_recorded_data_snapshot_type_idx on who_va_recorded_data (snapshot_type);
