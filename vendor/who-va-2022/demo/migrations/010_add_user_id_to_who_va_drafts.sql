alter table who_va_drafts add column if not exists user_id text;

update who_va_drafts d
set user_id = f.user_id
from who_va_form_entries f
where d.user_id is null
  and d.id = f.uid
  and f.user_id is not null;

create index if not exists who_va_drafts_user_id_idx on who_va_drafts (user_id);
