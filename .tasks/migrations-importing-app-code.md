---
title: Nothing stops a migration from importing live application code
doc_type: task
status: done
owner: engineering
last_updated: 2026-09-19
---

# Nothing stops a migration from importing live application code

Split out of `.tasks/pii-registry-fails-open-for-non-who-forms.md` ("Related,
same shape") when the two PII items there were closed.

A migration that calls application code pins itself to whatever that code
means *today*, not what it meant when the migration was written. The
`mas_org_unit` break came from four historical migrations calling
`build_submission_analytics_core_mv_sql()`.

## Survey result (2026-09-19)

An `ast` walk of every file in `migrations/versions` — module level and
inside functions — found **exactly 15** files importing `app.*`, and every
one of them imports only from `app.services.submission_analytics_mv`:

- **No migration imports `app.models`**, or any other `app.*` module. The
  task's guess that "most are probably model or enum imports (harmless)" was
  wrong: all 15 are the not-harmless kind, MV SQL builders.
- 13 import a single builder; `ab8c9d0e1f2a` and `e2f3a4b5c6d7` also import
  the `DEMOGRAPHICS_MV_NAME` constant; `e95dc3d7c4f2` (the three-way MV
  split) imports three builders.

## Closed by

- `tests/migrations/test_no_app_imports_in_migrations.py` — `ast`-based
  check with the 15 files pinned by filename *and* by the exact set of names
  each imports, so a pin cannot grow. Fails on unpinned imports, grown pins,
  stale pins and vanished files. Has positive and negative controls for the
  checker itself.
- The pairing empty-database replay already existed:
  `tests/migrations/test_schema_drift.py` builds `minerva_test_drift` from
  nothing, runs `alembic_upgrade(revision="heads")` and compares against the
  models. Nothing new was needed; the new module's docstring references it.
- Rule 7 in [`docs/policy/migration-chaining.md`](../docs/policy/migration-chaining.md):
  no migration imports application code; an MV rebuild copies the SQL in; the
  15 pins may be inlined, never extended.
