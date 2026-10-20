---
title: Case list query plans
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-20
---

# Case list query plans

Merge gate of [Case List Views](../policy/case-list-views.md) (digitva-pt0s):
`EXPLAIN (ANALYZE, BUFFERS)` of the statements behind `GET /api/v1/cases`.

```
docker compose exec -T minerva_app_service uv run --no-sync \
    python scripts/explain_case_list.py [--email testadmin@digitva.com] [--preset deaths] [--synthetic-rows 200000]
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
is an OR of three rules and a status `CASE`, so no single index applies. At
about 1.4 ms per 1 000 rows it is acceptable into the low hundreds of
thousands of cases, and it is the statement to watch. No migration was added.
Candidates if staging shows a problem (each an additive migration, check
`flask db heads` before and after): a composite `(project_id, created_at,
death_id)` for the page, and for the counts a cached or materialised per-scope
count instead of an index.
