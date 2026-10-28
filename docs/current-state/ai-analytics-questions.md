---
title: AI Analytics Questions
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-28
---

# AI Analytics Questions

Policy: [ai-analytics-questions.md](../policy/ai-analytics-questions.md).
Bead `digitva-qwvt`.

## Page and routes

`/data-management/ai-questions` (`app/routes/ai_questions.py`, on the
`data_management` blueprint), for data managers (`dm_grant_scope`) and admin.
Every POST returns an htmx partial, sends CSRF in `X-CSRFToken` and is
rate-limited per user:

| Route | Limit | Does |
| --- | --- | --- |
| `POST /ask` | 10/min | model question (quota, audit) |
| `POST /builtin/<key>/run` | 30/min | built-in report, no model |
| `POST /catalog/<key>/run` | 30/min | catalog question, no model |
| `POST /breakdown` | 60/min | side drawer counts |
| `POST /saved`, `/saved/<id>/run`, `/saved/<id>/delete` | 30/min | own saved queries |

The page runs `?saved=<id>` (own saved query) and `?catalog=<key>` once on
load, then removes the parameter from the address so a refresh does not run
it again. Search suggestion links use these. An htmx request over a limit
gets a 429 alert partial (`app/routes/va_errors.py`), not a redirect.

Layout: result area and the conversation's question history (held in the
page only); a side column with suggestions search (`/help/search`),
built-in reports, catalog questions and saved queries; a command bar pinned
to the bottom with the question box, the provider choice (enabled providers
only), the personal-data warning and follow-up chips (up to 3 from the
model). Clicking a chart segment, or a row's Breakdown button, opens an
offcanvas drawer with that category's counts by sex, age band and workflow
state. Chart.js is the vendored `app/static/vendor/chartjs`.

## Services

- `app/services/ai_analytics_sandbox.py`: `validate_sql` (pglast parser:
  one SELECT, only `ai_cube` and its own CTE names, an allowlist of
  functions, operators, casts and node types, text constants at most 200
  characters, no `||`); the per-request `ai_cube` temp table (core MV inner
  join demographics MV, as the analytics API, outer join COD snapshot, scoped
  by `dm_grant_scope` + `_mv_scope_filter`); `run_query` through
  `digitva_ai_run` as `digitva_ai_reader`; `explain_query`; `breakdown`
  (server SQL as the app user, whitelisted column, bound value); after each
  run `pg_advisory_unlock_all()`.
- `app/services/ai_analytics_providers.py`: `anthropic` (Claude,
  `client.beta.messages.create`, structured JSON output, effort low, medium
  on retry, cached system instruction, server-side refusal fallback) and
  `gemini` (Vertex AI or API key, thinking level minimal, low on retry).
- `app/services/ai_analytics_planner.py`: the system instruction and plan
  schema, quota, turn cap, retry with the redacted error, audit, saved
  queries, built-in and catalog runs. Each model call's input carries,
  beside the question, `ai_analytics_tables.scope_places`: the caller's
  projects (`project_id`, name, nickname; `_scope_projects`, as
  `ai_org_levels`) and, up to `MAX_SCOPE_SITES` (50), the sites of their
  project and site grants (`project_id`, `site_id`, name; the pairs
  `_mv_scope_filter` admits). Unit grants list their project but no sites.
  `sites` is absent when empty. A system-instruction rule makes the model match
  the question's wording against these and filter on the exact value, so
  "KEM" becomes `KEM001` rather than a guessed `project_id = 'KEM'`
  (`digitva-g72d`). The lists go
  in the user message, not the system instruction, so the provider's cached
  system prompt stays cached. `project_code` is not sent: it differs from
  `project_id` (ICMR01 is I1800).
- `app/services/ai_analytics_tables.py`: the temp tables a run may read,
  each built only when the SQL names it, with the reader granted `SELECT` on
  exactly those:
  - `ai_cube`: case counts, adding narration language, org unit names by
    depth (`org_l1_name`..`org_l7_name`), consent mode and the final-saved
    month and week;
  - `ai_org_levels`: level names per project;
  - `ai_staff`: staff counts per project, site, unit and role, with no
    names, scoped like the caller's Users page (`authz.user_list_filter`);
  - `ai_coder`: named coder results per coder, project and month (finals,
    allocation-to-final minutes, SmartVA match, exact ICD match, reviewer
    changes, not codeable, unknown cause, DORIS flags), for coders whose
    work falls in the caller's case scope.
  
  No table holds a case id or narrative.
- `app/services/ai_analytics_catalog.py`: 12 built-in reports and the
  catalog loader and writer.
- `app/services/ai_analytics_render.py`: Chart.js config (including the
  `comparison` chart with a reference line), table, KPIs and the drawer
  hook.
- **Not-captured answers:** the plan schema carries `answerable` and
  `not_captured`. The model answers "This data is not captured in DigitVA:
  …" for data DigitVA does not hold (population or catchment, time on
  screen) and writes no SQL. These are audited with `error_code`
  `not_captured`.

## Data

- Migration `a9e4c7f2b3d6`: role `digitva_ai_reader`, function
  `digitva_ai_run(text, integer)` (SECURITY DEFINER, `search_path`
  `pg_catalog, pg_temp`, `work_mem` 16MB, `temp_file_limit` 256MB; streams
  rows and raises SQLSTATE 54D01 past 1MB of JSON, the second argument may
  only lower that), tables `va_ai_saved_queries` and `va_ai_query_audit_log`
  (with `provider` and `model`). Public demo purge deletes both tables' rows
  for a purged account.
- `temp_file_limit` is a superuser parameter. The migrating user must be a
  superuser (as on dev), or on PostgreSQL 15+ hold
  `SET ON PARAMETER temp_file_limit WITH GRANT OPTION`, because the migration
  runs `GRANT SET ON PARAMETER temp_file_limit TO digitva_ai_reader` (the
  function applies the setting as its owner). The grant, like the role, is
  cluster-wide and survives a downgrade.
- `app/data/ai_question_catalog.json` (shown in
  [ai-question-catalog.md](../kb/ai-question-catalog.md)): 94 hand-written
  questions, many comparative (peer average or median, rank, period
  change), validated and run on dev; `flask ai-catalog generate [--provider] [--count] [--as]`
  replaces it with model-written questions that pass the parser and
  `EXPLAIN` as the reader.

## Configuration

`AI_ANALYTICS_ENABLED`, `AI_ANALYTICS_WEEKLY_QUOTA` (default 50),
`ANTHROPIC_API_KEY`, `AI_ANALYTICS_MODEL_ANTHROPIC` (default
`claude-sonnet-5-5`), `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`
(default `asia-south1`), `GOOGLE_APPLICATION_CREDENTIALS`, `GEMINI_API_KEY`,
`AI_ANALYTICS_MODEL_GEMINI` (default `gemini-3.5-flash`). All empty in
`.env.example`.

## Suggestions search and Typesense

`app/services/ai_search_service.py` serves `GET /help/search`. It indexes
help pages, active WHO VA cause definitions, catalog questions and saved
query titles and descriptions (owner-only). Saved queries are indexed on
save and removed on delete (best effort; skipped while Typesense is not
configured); `flask ai-search reindex` rebuilds everything, saved queries
included, and drops documents that no longer exist. When Typesense is
unreachable, search falls back to an in-process match plus `pg_trgm` over
the caller's saved queries.

Container `minerva_typesense_service` (`docker-compose.yml`): pinned image
`typesense/typesense:30.2`, 192 MB memory limit, internal network only (no
host port), volume `typesense_data`, `restart: on-failure:5` (it exits while
`TYPESENSE_API_KEY` is empty). The app reads `TYPESENSE_HOST`,
`TYPESENSE_PORT` and `TYPESENSE_API_KEY`.

## Known limits

- **Interviewer results are not built.** The tables module lists the
  interviewer per case as not captured, but the owner decided (2026-10-27)
  that the interviewer is `va_data_collector`, which DigitVA Collect sets
  from the signed-in user. An `ai_interviewer` table is a follow-up.
- **Level-name matching:** staffing questions by level (for example
  sub-centre) match each project's level names, which vary ("SC-AAM /
  Sub-centre"), so a level-type column is a follow-up. Live test: Claude
  matched "sub-centre" exactly and got no rows.
- **Renderer:** KPI cards add up percentage columns, and column labels show
  raw names. The switch to ECharts is a follow-up (owner 2026-10-27).
- **Question bank:** the rows in `.tasks/digitva-qwvt-question-bank.md` are
  not yet marked built or not captured.

- The weekly quota is read before the model call: concurrent asks can each
  pass at the last remaining call (overshoot of one call per concurrent
  request).
