---
title: Case list query plans
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-21
---

# Case list query plans

Merge gate of [Case List Views](../policy/case-list-views.md) (digitva-pt0s):
`EXPLAIN (ANALYZE, BUFFERS)` of the statements behind `GET /api/v1/cases`.

```
docker compose exec -T minerva_app_service uv run --no-sync \
    python scripts/explain_case_list.py [--email testadmin@digitva.com] [--preset deaths] [--synthetic-rows 200000] [--jit-off] [--outside-rows N] [--try-sql 'CREATE INDEX ...']
```

The script runs `list_cases` and `case_list_counts` once, captures the SELECTs
exactly as issued, and prints each plan (page, counts, supervision tiles).
`--synthetic-rows N` copies one in-scope case N times inside the transaction,
runs `ANALYZE`, explains, and rolls back (verified: `va_death_register` keeps
its 14 rows). **Staging data was not available**; the dev dataset has 14 case
rows, whose plans (sequential scans over 14 rows) say nothing about scale.

## Result on dev, testadmin, synthetic 200 000 rows (2026-10-20)

All copies sit in one project where testadmin holds a data_manager grant, so
nearly every row is in scope.

| Statement | Plan | Time |
| --- | --- | --- |
| Page (`deaths`, limit 50) | `Index Scan Backward using ix_va_death_register_created`, scope and status as filters, joins by primary key; stops at the limit | 3.8 ms |
| Counts (one aggregate) | `Seq Scan on va_death_register` over all 200 006 rows, scope OR filter | 290 ms |
| Tiles (`supervision_tiles`, as before) | `Seq Scan on va_death_register`, same scope | 303 ms |

Reading: the page walks the `created_at` index and stops early; that is the
best case, since the scope matched nearly every row. A narrow scope (an
interviewer at one unit among many projects) filters most index entries away
before it fills a page, so staging must be checked with a narrow user as well.
The API therefore computes counts and tiles on the first page only (a request with a `cursor` omits both), so paging past page one never pays them.
The counts and tiles aggregates are sequential scans by construction: the scope
is an OR of five or six rules (project/site/org-unit grants, project-wide
grants, a `va_sid` subquery) and a status `CASE`, so no single index applies.

## Composite index experiment (2026-10-21, digitva-kzyp)

Question: would `(project_id, created_at, death_id)` or `(project_id,
updated_at, death_id)` help the page or the counts? Method: the script's
`--try-sql` runs `CREATE INDEX` inside the rolled-back transaction, then
explains; `--outside-rows` copies a case of an out-of-scope project
(`DEMO01`) so the user's scope is a minority (20 000 in scope, 180 000 not).
`--jit-off` is shown separately because JIT dominates the counts statement
(its estimated cost is in the millions, so PostgreSQL compiles it: 466 ms of
the 704 ms below). Times in ms, `EXPLAIN (ANALYZE, BUFFERS)`, dev database.

| Scenario | Index | Page | Counts | Tiles |
| --- | --- | --- | --- | --- |
| 200 000 in scope, JIT on (default) | none | 3.8 | 703.7 | 304.1 |
| 200 000 in scope, JIT off | none | 3.9 | 246.6 | 70.0 |
| 200 000 in scope, JIT off | `(project_id, created_at, death_id)` | 3.9 | 247.3 | 69.2 |
| 20 000 in scope of 200 000, JIT off | none | 5.0 | 61.5 | 25.4 |
| 20 000 in scope of 200 000, JIT off | `(project_id, created_at, death_id)` | 4.4 | 80.9 | 49.3 |
| same, `enable_seqscan = off`, JIT off | `(project_id, created_at, death_id)` | 2.1 | 96.0 | 61.2 |

Result: **the planner never used the new index, even with sequential scans
disabled.** The page already stops early on `ix_va_death_register_created`
(3 to 5 ms) and the scope OR cannot be answered by a project-prefixed index
(its `va_sid` and hashed-subquery branches force a full read), so the counts
and tiles still scan the whole table: about 1.2 ms per 1 000 rows with JIT off,
which grows linearly. The `updated_at` variant is the same shape and was not
tried separately. **No migration was added**: an index the plans do not use
only slows writes. Head stays `c7e3a9d1f5b2`.

Applied (digitva-kzyp stage 5): `case_list_counts` runs the counts and tiles
statements under `SET LOCAL jit = off` and puts the caller's `jit` value back
afterwards (703 to 247 ms for counts, 304 to 70 ms for tiles, no schema
change). What would help next: cache the counts per scope (short TTL) if the table
reaches the low hundreds of thousands of cases in one scope.
