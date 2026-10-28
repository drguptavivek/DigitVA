---
title: AI Analytics Questions Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-28
---

# AI Analytics Questions Policy

## Purpose

Users who already see aggregate analytics may ask a question in plain
language. An external language model turns
the question into SQL. DigitVA runs that SQL over aggregated counts the user
is already allowed to see and draws the result as a chart and a table.
Tracked in `digitva-qwvt`.

## Owner decision (2026-10-27)

The model may see **aggregates only**. It never sees a submission, a person
or any field that identifies one.

## What leaves DigitVA

Only three things are sent to the model provider:

1. A fixed system instruction: the aggregate table's column names and types,
   the allowed code values, SQL rules and example queries. It contains no data
   values from submissions. KPI definition text from the KPI registry
   (`app/data/kpi_registry.json`; owner decision 2026-10-27, `digitva-r5s0`)
   may be included in it, so the model can say which KPI a question maps to.
   That is definition text (a name, a question, a formula in words), not data.
2. The user's question, plus on a follow-up the previous SQL and up to five
   earlier questions. With it go the id, name and nickname of each project
   in the user's AI table scope; when there are at most 50, the id and name
   of each site under their project and site grants (not under org unit
   grants). The model then uses exact project and site codes and names rather
   than guessing them (`digitva-g72d`). Project and site codes and names are
   not personal data; nothing else about them (address, phone, coordinates)
   is sent.
3. On a retry, the error for the SQL the model wrote: the SQLSTATE and
   PostgreSQL's primary message with every quoted value replaced by
   `<value>`, or the SQL check's own refusal text. The user may see the full
   message.

Version 1 sends **no result rows** to the model. The summary under a chart is
built by DigitVA from the result. If a model-written summary is added later,
it may receive only result rows from the aggregate table, with every count
below 5 replaced by `<5`, at most 200 rows. That change needs an update to this
policy first.

A user can still type identifying text into a question. The question box
warns against this: "Do not type names, phone numbers or other personal
details; this question is sent to an external AI service". Questions are kept in the audit
log under the same retention as other audit logs.

## What the generated SQL can read

- Each request builds a transaction-local temporary table, `ai_cube`. It is
  built from the analytics materialized views and filtered by the same scope
  the analytics API uses (`dm_grant_scope` and `_mv_scope_filter`). That scope
  includes the retired-submission and confirmed-duplicate exclusions.
- `ai_cube` holds counts grouped by low-risk dimensions only. It has no
  `va_sid`, unique id, name, narrative, free text, raw age, date of birth,
  GPS or staff identity. Its grain (extended below) is project, site, month, sex, age band,
  workflow state, final cause source, WHO 2026 VA cause section and cause,
  ICD code, SmartVA top cause bucket and NQA rating.
- Generated SQL runs as the `digitva_ai_reader` database role. That role
  has `SELECT` on `ai_cube` and nothing else, inside a `READ ONLY`
  transaction with `statement_timeout` 5 s, and returns at most 500 rows.
  The database enforces these limits. The function also caps `work_mem` at
  16MB and temp files at 256MB, and refuses a result whose JSON passes 1MB
  ("result too large", not retried with the model).
- Before it runs, all SQL (model answers, saved queries, built-in reports and
  catalog questions alike) is parsed with PostgreSQL's parser and accepted
  only as one `SELECT` that reads `ai_cube` and its own `WITH` names, calls
  only allowlisted aggregate, scalar and window functions, casts only to
  basic scalar types, has no `WITH RECURSIVE`, locking or `INTO`, no `||`,
  no text constant over 200 characters, no numeric constant over 20
  characters or with an exponent over 20, at most 4 `FROM` items in total
  (`ai_cube`, a `WITH` name or a subquery, at any depth) and at most 8
  `WITH` names. The
  database caps time, rows, output size, temp files and privileges but not
  the memory one value takes, so this check is what stops a memory bomb. A
  text check (one statement, starts with `SELECT` or `WITH`) runs first.
- After every run the app releases any session-level advisory lock on the
  connection before it returns to the pool.
- The scope is resolved for the caller on every run, saved queries included.
  A saved query stores SQL and a chart recipe, never a scope.

## Tables, staff results and "not captured" (owner, 2026-10-27)

The owner approved everything in the question bank
(`.tasks/digitva-qwvt-question-bank.md`), built only from data already in the
main PostgreSQL database.

- **`ai_cube` gains** the narration language, the case's org unit and its
  ancestor names at each level of the project's hierarchy (with
  `ai_org_levels` naming the levels per project), consent mode, and the month
  and ISO week the final cause was saved.
- **`ai_staff`** holds staff counts per project, site, org unit and role. It
  has no names: active grants, users signed in within 7 and 30 days, users who
  never signed in, unverified emails, and coders per coding language. Training
  figures are included only where DigitVA stores them.
- **`ai_coder` and, if the source is captured, `ai_interviewer`** hold named
  staff results, one row per person per month. Each row carries the display
  name and that person's unit, and only metrics derived from stored data:
  - finals saved;
  - elapsed minutes from allocation to final save (median and share under 3
    minutes). This is elapsed time, not time on screen;
  - share of finals matching SmartVA's top cause (overall and when SmartVA's
    likelihood is low);
  - share changed by a reviewer;
  - not-codeable count and unknown-cause share;
  - DORIS rejections, warnings and age/sex confirmations, where stored.

  No case identifier, narrative or deceased detail is in these tables.
- **Who sees names:** only data managers and admins, and only for staff whose
  work falls in their own scope. They already see these people on the People
  page. The model still never sees a row, so names never leave DigitVA. Saved
  queries store SQL, not results.
- **Comparative answers:** the model is told to prefer comparisons (a unit
  against its peers' average or median, rank, this period against the last
  and the same month last year, change and percent change). The chart
  `comparison` type draws a reference line for the peer value.
- **"Not captured":** every answer states whether the data can answer the
  question. The fixed instruction lists what DigitVA does not store
  (population or catchment, time actually spent on screen, and any other item
  found missing while building). When a question needs data DigitVA does not
  store, the model must answer "This data is not captured in DigitVA: <what
  is missing>" and write no SQL. The page shows that answer as it is.

## Who may use it

The same users as `/api/v1/analytics` (data managers, as resolved by
`dm_grant_scope`, including admin). Other roles get it only through a later
policy change. The training project is excluded, as it is in analytics.

## Cost and fair use

- Each model call is logged in `va_ai_query_audit_log`: user, mode, question,
  SQL, turn, retry flag, provider, model and token counts.
- Model calls per user are limited per ISO week by `AI_ANALYTICS_WEEKLY_QUOTA`
  (default 50). Admins have no limit.
- Rerunning a saved query makes no model call and uses no quota.
- A conversation has at most 6 turns: the first question and 5 follow-ups.
  After that the user starts a new question.

## Providers (owner, 2026-10-27)

Two providers are supported under the same rules. A provider is enabled
when its credentials are configured. The user picks any enabled provider for
each question; the first enabled provider in the list below is the
default. The audit log records the provider and model used for every call.
Rerunning a saved query needs no provider.

- `anthropic` (default; the owner has Anthropic credits): Claude Sonnet
  (`claude-sonnet-5-5`) through the Anthropic API. It uses structured JSON
  output, `effort: low`, prompt caching on the fixed system instruction, and
  the server-side refusal fallback. Its key is `ANTHROPIC_API_KEY`, from the
  deployment's secrets.
- `gemini`: Google Gemini (`gemini-3.5-flash`) on Vertex AI, configured
  through `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` (default
  `asia-south1`, availability to be confirmed), with Google Application
  Default Credentials; or the Gemini API with `GEMINI_API_KEY`.

Neither provider processes the data in India by default. That is acceptable
only because no submission data is sent (see "What leaves DigitVA").

## Per-project AI provider and key: bring your own key (owner, 2026-10-27)

A project can use its own AI account in place of the platform's.

- **What a project stores:** one or more provider credentials.
  - `anthropic`: an API key.
  - `gemini`: an API key, or Vertex AI (project id, location and a
    service-account JSON).
  - Each credential has a model override (optional), a monthly
    question cap (optional), and an on/off switch.
- **Who manages it:** admins and the project's PI, in Project Setup.
  - The key is **write-only**: once saved it is never shown again, only its
    provider, the last 4 characters, who saved it and when.
  - Replacing or deleting a key is audited (who, when, which provider),
    never with the key itself.
  - On save DigitVA makes one minimal test call and refuses a key that
    fails.
- **How it is stored (post-quantum, owner 2026-10-27):**
  - Encrypted with DigitVA's PII envelope (`app/utils/pii_crypto.py`,
    `docs/policy/pii-envelope-format.md`): a fresh AES-256-GCM data key per
    value, wrapped with hybrid ML-KEM-768 + X25519 (FIPS 203). This is the
    same key management and rotation as PII.
  - The AAD binds each ciphertext to its project and credential id, so a
    ciphertext copied to another row will not decrypt.
  - The older `credential_crypto.py` (Fernet, AES-128) is not used for AI
    keys. ODK credentials move off it separately (`digitva-lep4`).
  - Decrypted only in the request that calls the provider. The plaintext may
    be cached in process memory for up to 5 minutes, never in Redis, the
    database or logs.
  - Exports, backups and the demo purge carry only ciphertext. The demo
    purge removes a demo project's credentials.
- **In transit:** calls to the providers use TLS 1.3 with the hybrid
  post-quantum key exchange X25519MLKEM768. The app image's OpenSSL 3.5.7
  negotiates it with `api.anthropic.com` and `aiplatform.googleapis.com`
  (checked 2026-10-27). An image whose OpenSSL lacks ML-KEM must not be
  deployed.
- **Which key a question uses:**
  - Questions run in one project's context. The page gets a project
    selector, defaulting to the user's only project.
  - With a project chosen, `ai_cube` and the other tables are limited to
    that project, and the project's own credential is used when one is set
    and switched on. Otherwise the platform credential is used, if the
    platform has one.
  - "All my projects" uses only the platform credential. The provider list
    shows only providers that have a usable credential in the chosen
    context.
- **Cost and limits:**
  - The audit log records the project and whether the platform or the
    project key paid.
  - A project's monthly cap stops model calls on its key once reached.
    Saved queries, reports and the catalog are unaffected.
  - Weekly per-user quotas still apply.
- **What stays the same:** the aggregates-only rule, the SQL sandbox and
  everything under "What leaves DigitVA" apply whoever's key is used. A
  project's own key does not let it send more data.

## Configuration

The feature is off unless `AI_ANALYTICS_ENABLED` is set.
`AI_ANALYTICS_MODEL_ANTHROPIC` and `AI_ANALYTICS_MODEL_GEMINI` override each
provider's default model (implementation, 2026-10-27: one shared
`AI_ANALYTICS_MODEL` cannot name a model for two providers). No key or
project id is hard-coded or committed. While the feature is off, saved
queries still run.

## Database privileges (digitva-weiq)

The reader role `digitva_ai_reader` and the function `digitva_ai_run` need
more than a normal app user holds: CREATE ROLE or an existing role the user is
a member of, and on PostgreSQL 15+ `SET ... WITH GRANT OPTION` on
`temp_file_limit` (a superuser-only parameter). Migration `a9e4c7f2b3d6` checks
this (superuser, or the role exists, the user is a member, holds the grant
option, and the role may create in the schema). If not, it skips the role and
function, prints a warning and still creates the tables, so a non-superuser
deploy (staging) boots. A superuser then runs
`psql -v app_user=<app user> -d <app database> -f deploy/sql/ai_reader_setup.sql`
once (idempotent). Until then every AI question, saved-query rerun and report
answers "not configured" (503), never a 500.

## Phase 2 (owner: good to have, 2026-10-27)

- **Built-in reports.** These are fixed SQL queries over `ai_cube`, run with
  no model call and no quota. They cover the operational and mortality
  outcome questions the cube can answer: the workflow funnel, intake and
  state mix, NQA rating mix, cause share by WHO 2026 VA cause and age band,
  top ICD codes, monthly trends, and SmartVA vs final cause agreement by
  bucket. Staff activation and performance reports need staff-level data,
  which this policy excludes. They need a separate policy.
- **Question catalog.** A command (`flask ai-catalog generate`) asks the model
  for common questions with SQL. It sends only the system instruction. Each
  query is checked with `EXPLAIN` against `ai_cube` as `digitva_ai_reader`.
  The result is committed as `app/data/ai_question_catalog.json` and
  `docs/kb/ai-question-catalog.md`. Choosing a catalog question runs its
  stored SQL with no model call.
- **Suggestions.** Typo-tolerant suggestions come from a Typesense
  container in the Compose stack. It has a pinned image, a 192 MB memory
  limit and an internal network only. It indexes catalog questions, the
  user's own saved-query titles and keywords, help pages (the registry in
  `app/routes/help.py`, each page carrying its `roles` list so results
  follow the same filter as `_visible_pages`), and active WHO VA cause
  definitions (`mas_va_cause_definitions`: code, title, text with HTML
  stripped). It never indexes SQL results or submission data. A help or
  definition result links to its existing page; it never runs a query. When Typesense is unavailable, search falls back to
  `pg_trgm` over saved queries and an in-process match over the catalog.
- **Workspace UI.** A command bar pinned to the bottom with follow-up chips,
  a question history for the current conversation, and a side drawer. Clicking
  a chart segment opens the drawer with a breakdown from `ai_cube`, never
  individual submissions. The follow-up chips are up to three short
  questions the model returns with its plan; built-in reports and catalog
  questions have none. The drawer's SQL is written by DigitVA (a
  whitelisted `ai_cube` column, a bound value), runs as the app user inside
  the same transaction before the role switch, and is never sent to a model.
- Built-in report and catalog runs make no model call and write no audit
  row (implementation, 2026-10-27).

## Not planned

Drill-down to individual submissions, shared saved queries (site, project or
global), coder self-view ("my backlog", "my speed"), and any role beyond the
analytics users. Each needs a policy change first.
