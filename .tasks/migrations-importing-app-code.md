---
title: Nothing stops a migration from importing live application code
doc_type: task
status: open
owner: engineering
last_updated: 2026-09-19
---

# Nothing stops a migration from importing live application code

Split out of `.tasks/pii-registry-fails-open-for-non-who-forms.md` ("Related,
same shape") when the two PII items there were closed. Unchanged in substance.

A migration that calls application code pins itself to whatever that code
means *today*, not what it meant when the migration was written. The
`mas_org_unit` break came from four historical migrations calling
`build_submission_analytics_core_mv_sql()`.

`grep` finds 15 migration files importing from `app.*`. Most are probably
model or enum imports, but nobody has swept them.

## Proposed close

- sweep the 15 files and record which imports are model/enum (harmless) and
  which reach into `app.services` (not harmless)
- add a lint that fails on `app.services` imports inside
  `migrations/versions`
- pair it with the empty-database `flask db upgrade` replay, which is now
  known to work
