---
title: Dev DB stamp went backwards, and other infra findings
doc_type: task
status: open
owner: engineering
last_updated: 2026-09-19
---

# Dev DB stamp went backwards, and other infra findings

## 1. The dev database moved back two revisions, cause unknown

On 2026-09-19 the shared dev database was observed at `b8e3d1f7a2c4`, then
later at `a40c38e73af4` — two revisions **earlier**. Nobody claimed the change.

It was not a clean downgrade. The database still held everything the two later
migrations produce: the `WHO_2022_VA_2026` scheme from `c5f2a8d1e9b3` and 31
`is_pii`-flagged fields from `b8e3d1f7a2c4`. So `alembic_version` disagreed
with the data.

Resolved by re-running `flask db upgrade` after a full `pg_dump`. Both
migrations are idempotent and proved so: afterwards the scheme count is still
1, not 2, and the `is_pii` count still 31, not 62. Head is `b8e3d1f7a2c4`.

**The cause is still unknown and that is the open part.** A stamp that moves
backwards without a downgrade is a data-integrity signal. Candidates not ruled
out: a `flask db stamp`/`downgrade` from another tree, or a container restart
running `boot.sh` from a checkout that did not have the newer revisions. If it
recurs, capture `alembic_version` and the container logs before fixing it.

Related, and a likely contributor: the app image's `boot.sh` runs
`flask db upgrade` and **retries forever** against the dev DB from a tree that
lacks the revision the DB is stamped at. It hangs silently rather than failing,
so the operator sees a slow start rather than an error naming the mismatch.
That is worth a bounded retry and a clear message.

## 2. Unexplained 35-second stall in a full-suite run

One full-suite run failed `tests/test_admin_api.py::AdminApiTests::test_odk_site_mappings`
(`form_smartvahiv` was `'False'`, expected `'True'`). Its log shows the POST and
the GET each taking ~35,118 ms, identical to within 3 ms — consistent with a
shared stall such as connections cut mid-request, not with application logic.

Not reproduced: the file alone passes (42), and a full re-run passes (1,370).
Cause not established; an order-dependent flake is not ruled out. If it recurs,
the identical timings are the fingerprint to look for.

## 3. Smaller items seen and not chased

- Nobody has mutation-tested the test suites run today. Whether the new tests
  fail when the code is wrong is unverified, except for
  `tests/test_role_required_validation.py`, which was mutation-tested properly
  (see `docs/policy/test-harness.md` on defeating the bytecode cache).
- The `minerva_app` container showed `(unhealthy)` for a period and recovered.
  Not investigated.
- Stale connections on `minerva_test_kindboyd`, `minerva_test_a`, `_b`, `_c`.
  Ownership unknown.
- Three `SAWarning`s from `test_schema_drift.py` — the
  `mas_org_level`/`va_project_master` table-sort cycle, `ltree`, and
  `gin_trgm_ops`. They predate today's work. The sort cycle is **not
  cosmetic**: it caused a fixture to fail a foreign key after seeding its own
  parent row, because SQLAlchemy falls back to insertion order when it cannot
  topologically sort.
- `uv run` without `--no-sync` re-syncs the shared venv volume; use `--no-sync`.
