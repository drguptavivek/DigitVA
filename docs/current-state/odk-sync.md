---
title: ODK Sync And Attachments
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-19
---

# ODK Sync And Attachments

## Summary

ODK sync is an incremental batch process that:

1. Resolves active site-level ODK mappings
2. Materializes compatibility `va_forms` rows for those mappings
3. For each form, runs an OData filter-gated delta check — skips if nothing changed since last sync
4. Fetches changed submissions via OData JSON (paginated, no ZIP download)
5. Writes or updates `va_submissions` rows for all fetched ODK submissions, including consent=`no` and consent-missing rows
6. Reuses one pyODK client/session per `(connection_id, odk_project_id)` group across delta, fetch, targeted single-record refresh, and attachment sync
7. Per-form commit — earlier forms are not rolled back if a later form fails
8. Syncs attachments for upserted submissions using ETag-based conditional download
9. Rebuilds full CSV from DB for SmartVA compatibility
10. Records `last_synced_at` on the mapping row after each successful form
11. Marks local sync issues when a local submission is missing from active ODK submissions
12. Runs SmartVA on any new or updated submissions

## Known Issue: Workflow State Guards

> **WARNING**: The current implementation does NOT respect workflow state guards for `coder_finalized` submissions.
>
> When ODK data changes, the system unconditionally destroys all workflow artifacts including finalized CODs.
>
> See [ODK Sync Policy](../policy/odk-sync-policy.md) for the intended behavior and planned fixes.

## Connection Model

- ODK connection details are stored in `mas_odk_connections` (DB) with encrypted credentials
- Each project is linked to a connection via `map_project_odk`
- `va_odk_clientsetup(project_id)` resolves the connection from DB first, falls back to legacy `odk_config.toml` if no DB mapping exists
- pyODK `Client` is built using an explicit `Session` (base_url, username, password); a shared stub config file (`odk_stub_config.toml`) satisfies the file-read requirement without storing credentials
- Each connection uses its own cache file (`odk_cache_<connection_id>.toml`) so concurrent calls to different ODK servers do not share auth tokens
- Each DB-managed connection also stores shared guard state:
  - `cooldown_until`
  - `consecutive_failure_count`
  - `last_failure_at`
  - `last_failure_message`
  - `last_success_at`
  - `last_request_started_at`
- The legacy `odk_config.toml` fallback remains for projects not yet migrated to DB-managed connections

## Sync Entry Point

Main service:

- [`va_data_sync_odkcentral()`](../../app/services/va_data_sync/va_data_sync_01_odkcentral.py)

Behavior:

- Loads active `map_project_site_odk` rows for active project-site assignments
- Upserts compatibility `va_forms` rows for those mappings
- Captures `snapshot_time = datetime.now(UTC)` before any ODK calls
- Loops over forms, running the delta check → fetch → upsert → attach → commit pipeline per form

Important detail:

- `map_project_site_odk` is the source of truth for what gets synced
- `va_forms` still exists because submissions, media storage, permissions, and several workflow paths key off `va_form_id`
- Sync materializes `va_forms` rows from the site mapping table rather than requiring admins to manage both separately
- the sync loop now groups forms by `(connection_id, odk_project_id)` and
  reuses one pyODK client across every form in that group for delta checks,
  OData fetches, and attachment requests

## Delta Check (Phase 1)

Before fetching any submission data, the sync runs a lightweight OData count:

```
GET /v1/projects/{id}/forms/{formId}/submissions.svc/Submissions
  ?$filter=(__system/submissionDate gt T) or (__system/updatedAt gt T)
  &$top=0&$count=true
```

Implemented in [`va_odk_delta_count()`](../../app/utils/va_odk/va_odk_05_deltacheck.py).

Rules:

| Condition | Action |
|---|---|
| `mapping.last_synced_at` is NULL | First-ever sync — always download |
| Delta count = 0 | Run gap check (compare ODK IDs vs local) |
| Delta count > 0 | Proceed to full OData JSON fetch |
| ODK error / timeout | Run gap check as safe fallback |

`snapshot_time` is captured before any ODK calls. `last_synced_at` is set to `snapshot_time` (not wall clock) after a successful form sync. This ensures submissions arriving mid-run are caught on the next sync rather than missed.

## Gap Sync (Phase 1b)

When the delta count is 0 or the delta check fails, the sync runs a gap check instead of skipping the form entirely. This catches submissions that were missed by earlier failed syncs.

Steps:

1. Fetch all ODK submission instance IDs via `GET /v1/projects/{pid}/forms/{fid}/submissions` (single REST call, metadata only)
2. Load all local `va_sid` values for the form
3. Compare local rows to active ODK IDs and flag local submissions missing from ODK as a sync issue
4. Compute missing IDs: ODK IDs that don't have a corresponding local `{id}-{form_id.lower()}`
5. If no missing IDs → skip form (truly in sync from a fetch perspective)
6. Fetch missing submissions in batches of 50 via OData single-entity access `Submissions('{instanceId}')`
7. Upsert and commit each batch independently for crash resilience

Implemented in:

- [`va_odk_fetch_instance_ids()`](../../app/utils/va_odk/va_odk_06_fetchsubmissions.py) — lightweight ID listing
- [`va_odk_fetch_submissions_by_ids()`](../../app/utils/va_odk/va_odk_06_fetchsubmissions.py) — targeted fetch by instance ID

Note: OData `$filter` on `__id` is not supported by ODK Central (HTTP 501). The single-entity access pattern `Submissions('{instanceId}')` is used instead.

### Local sync-issue tracking

DigitVA now stores local sync-health markers on `va_submissions`:

- `va_sync_issue_code`
- `va_sync_issue_detail`
- `va_sync_issue_updated_at`

Current code written by the runtime path:

- `missing_in_odk` — the submission exists locally but was absent from the
  current active ODK submission ID list for that form

The flag is cleared automatically if the submission reappears in a later sync.

## Submission Fetch (Phase 2)

Changed submissions are fetched via OData JSON (paginated, 250 per page):

```
GET /v1/projects/{id}/forms/{formId}/submissions.svc/Submissions
  ?$top=250&$skip=N
  &$filter=(__system/submissionDate gt T) or (__system/updatedAt gt T)
```

For first-ever syncs (`last_synced_at` is NULL), no filter is applied — all submissions are fetched.

Implemented in [`va_odk_fetch_submissions()`](../../app/utils/va_odk/va_odk_06_fetchsubmissions.py).

### OData JSON normalization

OData returns nested group objects. The fetch utility flattens them to leaf field names (equivalent to `groupPaths=false`) and maps `__system.*` fields to CSV column equivalents:

| OData field | Normalized name |
|---|---|
| `__id` | `KEY` |
| `__system/submissionDate` | `SubmissionDate` |
| `__system/updatedAt` | `updatedAt` |
| `__system/submitterName` | `SubmitterName` |
| `__system/reviewState` | `ReviewState` |

Nested group objects are recursively flattened to leaf names. Because WHO VA 2022 field names are globally unique, name collisions from flattening are not a concern in practice.

### CSV rebuild for SmartVA

After each form sync, [`va_odk_rebuild_form_csv_from_db()`](../../app/utils/va_odk/va_odk_06_fetchsubmissions.py) regenerates the full CSV from all `va_submissions.va_data` records. This ensures SmartVA-only runs have complete data even after an incremental sync that only fetched recent changes.

## Attachment Sync (Phase 2)

Attachments are downloaded per-submission using ETag-based conditional HTTP:

```
# 1. Fetch attachment list (no binary)
GET /v1/projects/{id}/forms/{formId}/submissions/{instanceId}/attachments
→ [{name: "audio.amr", exists: true}, ...]

# 2. Conditional download
GET /v1/projects/{id}/forms/{formId}/submissions/{instanceId}/attachments/{filename}
If-None-Match: <stored_etag>
→ 304 Not Modified  (skip — nothing transferred)
→ 200 + binary      (download — write file, update ETag record)
```

Current implementation detail:

- attachment downloads are streamed to disk in chunks rather than buffered via
  `response.content`
- ODK attachment requests use explicit connect/read timeouts from
  `ODK_CONNECT_TIMEOUT_SECONDS` and `ODK_READ_TIMEOUT_SECONDS`

Implemented in:

- [`va_odk_sync_submission_attachments()`](../../app/utils/va_odk/va_odk_07_syncattachments.py)
- [`va_odk_sync_form_attachments()`](../../app/utils/va_odk/va_odk_07_syncattachments.py)

Rules:

- attachment sync runs for submissions in `upserted_map` during full and
  single-form sync
- single-submission refresh also syncs attachments for that submission
- Submissions that already exist with unchanged `updatedat` receive zero attachment API calls
- Forms with delta = 0 receive zero attachment API calls
- The media directory is **never cleared** (`rmtree` eliminated) — files for unchanged submissions remain on disk

### ETag cache

ETag records are stored in `va_submission_attachments`:

| Column | Purpose |
|---|---|
| `va_sid` | FK → `va_submissions` |
| `filename` | Original filename from ODK |
| `local_path` | Path on disk (may differ — `.amr` stored as `.mp3`) |
| `mime_type` | Content-Type from download response |
| `etag` | ETag header from last successful download |
| `exists_on_odk` | Whether ODK reports the file as present |
| `last_downloaded_at` | When the file was last downloaded |

Primary key: `(va_sid, filename)`.

### Audio conversion

`.amr` files are converted to `.mp3` using `pydub` immediately after download. The `.amr` file is deleted after successful conversion. Conversion failure keeps the `.amr` on disk (better than data loss).

### API call volume

For each submission in `upserted_map`:

- 1 attachment-list API call (always)
- N download calls (one per new or changed file; 0 if all ETags match → 304)

On first sync of a large form: O(submissions) attachment-list calls are unavoidable. On subsequent syncs with no changes: 0 calls (delta check skips the form entirely).

### Auth/session reuse

The sync path now reuses one pyODK client per `(connection_id, odk_project_id)`
group for:

- delta check
- submission fetch pagination
- attachment list calls
- conditional attachment downloads

This reduces repeated auth/session verification calls from roughly
O(submissions) to roughly O(connection/project groups) during the
attachment-heavy parts of a sync run.

### Bounded parallelism

Attachment sync now processes changed submissions with a small bounded worker
pool per form:

- default worker cap is `3`
- network I/O and file writes happen in worker threads
- ORM record creation and updates are applied sequentially in the main thread

This keeps the sync run fully synchronous and only marks the form successful
after all attachment work completes, while reducing attachment wall-clock time
without sharing the Flask SQLAlchemy session across threads.

## Connectivity Retry Policy

ODK sync now applies bounded retry only at the form-fetch boundary.

Rules:

- delta-check timeout still falls through immediately to the full-download path
- the full OData fetch is retried only for retryable upstream failures such as:
  - connect timeout
  - connection error
  - request timeout
  - auth/session failures surfaced as token or 401/403-style errors
- retry budget is fixed at 3 attempts total
- backoff schedule is `5s`, then `10s`
- each retry refreshes the cached pyODK client for that
  `(connection_id, odk_project_id)` group before retrying
- after the final failed attempt, the form is marked failed for the run and the
  sync continues with later forms

This is intended to stop repeated hammering of ODK Central while still allowing
short-lived auth/connectivity faults to recover cleanly.

## Shared Connection Guard

DB-managed ODK connections now use a shared guard service across app and worker
processes.

Rules:

- every outbound ODK request for DB-managed connections reserves a per-connection
  request slot before the request is sent
- the minimum interval between request starts is configurable through
  `ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS`
- retryable connectivity/auth failures increment a shared consecutive-failure
  counter on `mas_odk_connections`
- once the configured failure threshold is reached, the connection enters
  cooldown until `cooldown_until`
- during cooldown, later callers fail fast without attempting a live upstream
  call
- successful calls reset the shared failure count and clear cooldown

This guard is used by:

- OData delta checks
- OData submission fetch pages
- attachment list and download requests
- admin live ODK project/form lookups
- admin connection tests
- ODK review-state write-back

Operator-facing visibility now exists in:

- the ODK Connections admin panel
- the Project Forms connection bar for the selected project
- the Sync Dashboard status card when any active ODK connection is degraded or
  in cooldown

Related policy:

- [ODK Connection Guard Policy](../policy/odk-connection-guard.md)

## Update Detection

During upsert:

- Submission exists with same `va_odk_updatedat` → skipped (no DB write, no attachment call)
- Submission exists with changed `va_odk_updatedat` → updated; active workflow artifacts deactivated
- Submission does not exist and consent is present and ≠ `no` → inserted (accepts `yes`, `telephonic_consent`, etc.)
- Submission does not exist and consent = `no` or is null → ignored

When a submission is updated, the app deactivates related local workflow artifacts:

- Active coder allocations
- Coder review records
- Initial assessments
- Final assessments
- Reviewer reviews
- User notes

ODK is treated as the source of truth for submission content.

> **NOTE**: This behavior does NOT respect `coder_finalized` state. See [ODK Sync Policy](../policy/odk-sync-policy.md) for the intended behavior.

## Language Normalization

During upsert, raw ODK language values (`narr_language` or `language` field) are normalized to canonical codes via `_normalize_language()`. This looks up the `map_language_aliases` table (cached per sync run). Unknown values pass through unchanged and appear in the admin Languages panel unmapped alert.

Example: `"Bengali"`, `"bn"`, `"bengali"` all normalize to `"bangla"`.

## Derived Data Added During Sync

After upsert, the app computes and stores:

- `va_summary`
- `va_catcount`
- `va_category_list`

The sync path also maintains:

- `va_submission_workflow`

Current behavior:

- newly inserted consented submissions are initialized as `ready_for_coding`
- updated submissions refresh their canonical workflow row after local
  workflow artifacts are deactivated

These are derived from mapping-driven preprocessing and drive UI rendering and workflow logic.

## Per-Form Isolation

Each form is committed independently. A failure on one form:

- Does not roll back earlier committed forms
- Does not update `last_synced_at` for the failed form (it retries next run)
- Is recorded in `failed_forms`; the overall run status becomes `partial`

## SmartVA During Sync

After all forms complete, SmartVA runs on any submissions without results:

- Prepares input CSV
- Runs SmartVA analysis
- Formats and stores results tied to the submission

## Sync Scheduling

Sync is driven by Celery beat using `celery-sqlalchemy-scheduler` DatabaseScheduler.

Tasks:

- [`run_odk_sync()`](../../app/tasks/sync_tasks.py) — full sync across all active forms; records outcome in `va_sync_runs`
- [`run_single_form_sync(form_id)`](../../app/tasks/sync_tasks.py) — force-resync one form, bypasses delta check
- [`run_single_submission_sync(va_sid)`](../../app/tasks/sync_tasks.py) — refreshes one local submission from ODK, syncs its attachments, and reruns SmartVA for that submission

Default schedule: every 6 hours (configurable via admin sync dashboard without restart).

Manual triggers:

- `POST /admin/api/sync/trigger` — dispatches `run_odk_sync.delay()`; returns 409 if a run is already in progress
- `POST /admin/api/sync/form/<form_id>` — dispatches `run_single_form_sync.delay(form_id)`
- `POST /vadashboard/data-manager/api/forms/<form_id>/sync` — dispatches scoped single-form sync for a data manager
- `POST /vadashboard/data-manager/api/submissions/<va_sid>/sync` — dispatches scoped single-submission refresh for a data manager

## Sync Run History

Every sync run is recorded in `va_sync_runs`:

| Field | Purpose |
|---|---|
| `sync_run_id` | UUID primary key |
| `triggered_by` | `"scheduled"` or `"manual"` |
| `triggered_user_id` | FK to `va_users` (manual runs only) |
| `started_at` | When the run began |
| `finished_at` | When the run ended (null while running) |
| `status` | `"running"` / `"success"` / `"partial"` / `"error"` |
| `records_added` | New submissions inserted |
| `records_updated` | Existing submissions updated |
| `progress_log` | JSON array of timestamped progress messages |
| `error_message` | First 2000 chars of exception or list of failed form IDs |

Status meanings:

| Status | Meaning |
|---|---|
| `success` | All forms succeeded or were delta-skipped |
| `partial` | At least one form failed, at least one succeeded |
| `error` | Task crashed or all forms failed |

Stale `running` rows (older than 45 minutes) are marked `error` automatically on worker restart and before each new sync run.

## ODK Coverage Check

A lightweight OData count utility:

- [`va_odk_delta_count()`](../../app/utils/va_odk/va_odk_05_deltacheck.py) — uses `$top=0&$count=true` with an optional `since` filter
- Returns total or filtered submission count without downloading any data

Also used by `GET /admin/api/sync/coverage` to compare ODK totals against local `va_submissions` counts per site mapping.

## Admin Sync Dashboard

Available at Admin Console → Data Sync (admin-only).

Sections:

- **Status bar** — last run outcome; auto-refreshes every 30s (5s while running)
- **Sync Now** — manual full sync trigger; 409 guard against concurrent runs
- **Stop** — shown only while a sync run is active; sends a revoke/terminate signal to the active Celery sync task and marks the run `cancelled`
- **Gen SmartVA** — trigger SmartVA-only run without ODK download
- **Schedule configurator** — change beat interval (1–168h) without restarting
- **Coverage table** — ODK total vs local total, last synced time, per-form force-resync button; loaded on demand rather than automatically on panel load
- **Progress log** — live timestamped entries; clears and resets when a new run starts
- **Run history** — last 20 runs with duration, trigger source, status, and error detail

## Local Storage Layout

```
data/
  <form_id>/
    <odk_form_id>.csv        ← rebuilt from va_submissions.va_data after each sync
    media/
      <filename>             ← attachment files (never cleared between syncs)
      <basename>.mp3         ← converted audio (original .amr deleted after conversion)
```

## Mapping Spreadsheets

Under `resource/mapping`:

- `mapping_labels.xlsx` — field display config and category ordering
- `mapping_choices.xlsx` — choice value mappings
- `icdcodes.xlsx` — ICD lookup data

These feed mapping generation used by preprocessing and rendering. They are not used during the ODK sync itself.
