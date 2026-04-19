---
title: ODK Sync And Attachments
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-19
---

# ODK Sync And Attachments

## Summary

ODK sync is an incremental batch process that:

1. Resolves active site-level ODK mappings
2. Materializes compatibility `va_forms` rows for those mappings
3. For each form, runs an OData filter-gated delta check — skips if nothing changed since last sync
4. Fetches changed submissions via OData JSON (paginated, no ZIP download)
5. Thin-upserts `va_submissions` rows for all fetched ODK submissions, including consent=`no` and consent-missing rows
6. Enriches the changed submissions for that same form into the canonical stored payload
7. Reuses one pyODK client/session per `(connection_id, odk_project_id)` group across delta, fetch, targeted single-record refresh, enrichment, and attachment sync
8. Per-form commit — earlier forms are not rolled back if a later form fails
9. Routes consent-valid changed submissions into `attachment_sync_pending`
10. Enriches changed submissions in bounded per-submission Celery batches so metadata work is checkpointed independently
11. Syncs attachments for upserted submissions using bounded Celery batch subtasks and ETag-based conditional download
12. Advances those submissions to `smartva_pending` only after all attachment batches for that form finish
13. Rebuilds full CSV from DB for SmartVA compatibility and then runs SmartVA for that same form
14. Records `last_synced_at` on the mapping row after each successful form
15. Marks local sync issues when a local submission is missing from active ODK submissions

## Current Identity Rule

Submission identity in the live sync path is based on the stable ODK submission
`KEY` (`__id` from OData), not on `instanceID`.

Current implementation:

- OData normalization maps `__id` to `KEY`
- OData normalization computes `sid` as `{KEY}-{form_id.lower()}`
- `instanceID` is stored as enriched metadata only
- the displayed `VA Form ID` on coding/data-manager pages comes from the
  business payload identifier (`va_uniqueid`), not from `va_submissions.va_sid`

Practical consequence:

- an ODK edit that changes `instanceID` but preserves `KEY` is still treated as
  the same DigitVA submission
- `instanceID` churn is metadata and should not be used as the canonical local
  sync key

## Current State: Not Codeable ODK Write-Back

Current behavior:

- coder Not Codeable attempts to write ODK review state `hasIssues` with a
  coder-specific comment after the local workflow save succeeds
- data-manager Not Codeable now follows the same pattern:
  - local `not_codeable_by_data_manager` save first
  - ODK `hasIssues` write-back second
  - role-specific comment text recorded in ODK
- ODK write-back failure does not roll back the local Not Codeable outcome
- success and failure are both auditable locally

## Current State: Workflow State Guards

The current implementation now respects protected-state sync guards for
finalized submissions.

Current behavior:

- ODK updates on protected submissions do not automatically destroy active COD artifacts
- the submission transitions to `finalized_upstream_changed`
- SmartVA is not regenerated automatically for that protected state
- the current runtime/API allows data managers or admins to accept or reject
  that protected-state transition
- the current runtime/API now exposes a normalized changed-fields diff for the
  pending protected update through:
  - `/api/v1/data-management/submissions/<va_sid>/upstream-change-details`
  - inline data-manager submission view
  - dashboard `View Changes` modal
- the sync path now stores a durable upstream-change record with:
  - prior workflow state
  - prior authoritative final-assessment id when present
  - previous VA payload snapshot
  - incoming VA payload snapshot
- the sync path now creates pending notification rows for:
  - `vaadmin`
  - `data_manager`

Current lineage note:

- runtime still treats `va_submissions` as the active submission row
- additive payload-version schema now exists:
  - `va_submission_payload_versions`
  - `va_submissions.active_payload_version_id`
- sync now writes active payload versions for newly created and payload-changed
  non-protected submissions
- sync now writes pending upstream payload versions for protected finalized
  submissions when upstream ODK data changes
- existing rows have been backfilled into initial active payload versions
- current protected-state lineage is preserved through
  `va_submission_upstream_changes`, which stores:
  - previous payload-version id
  - incoming payload-version id
  - previous VA payload snapshot
  - incoming changed VA payload snapshot
  - previous authoritative final-assessment id when present
- upstream accept now promotes the pending payload version to active and
  updates the active summary row
- upstream keep-current-ICD now also promotes the pending payload version to
  active, preserves finalized ICD/COD artifacts, and restores the prior
  finalized workflow state
- modal upstream review resolution is now local-only and does not post
  an ODK rejection comment
- protected sync updates no longer overwrite the active summary row before the
  accept decision
- normalized payload comparison now ignores volatile metadata and
  representation-only churn such as `updatedAt`, attachment counters, and
  numeric-vs-string-equivalent scalar values
- changed-field review presentation now separates:
  - data changes
  - metadata changes
  - formatting-only changes
- this gives current upstream-review lineage for protected updates, while the new
  payload-version schema is now the active lineage model for sync writes and
  protected upstream resolution
- SmartVA rows now also bind to `payload_version_id`
- coder and reviewer final-COD artifacts now also bind to `payload_version_id`
- final COD authority resolution now ignores stale coder/reviewer final rows
  from superseded payload versions

Current workflow follow-through after sync:

- screening-enabled projects may route submissions through
  `screening_pending -> smartva_pending` or
  `screening_pending -> not_codeable_by_data_manager`
- admin override and recode now use explicit workflow transitions
- the hourly coding-maintenance path now writes `reviewer_eligible` after the
  coder recode window expires when no active recode episode exists

Current naming:

- current implemented state key: `finalized_upstream_changed`
- legacy migrated key: `revoked_va_data_changed`
- preferred UI label: `Finalized - ODK Data Changed`

See [ODK Sync Policy](../policy/odk-sync-policy.md) for the policy baseline and
remaining implementation work.

## Current Workflow Execution Layer

ODK sync no longer writes canonical workflow states ad hoc.

Current runtime behavior:

- sync calls named transitions in `app/services/workflow/transitions.py`
- sync-originated transitions use the typed `vasystem` actor
- transition execution locks the target workflow row before validation and write
- `route_synced_submission()` now explicitly excludes protected source states,
  so finalized, reviewer-eligible, reviewer-finalized, and legacy-closed cases
  cannot be silently rerouted by a generic sync transition

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
- Loops over forms, running the delta check → fetch → thin upsert → enrich →
  attachments → SmartVA pipeline per form

Important detail:

- `map_project_site_odk` is the source of truth for what gets synced
- `va_forms` still exists because submissions, media storage, permissions, and several workflow paths key off `va_form_id`
- Sync materializes `va_forms` rows from the site mapping table rather than requiring admins to manage both separately
- the sync loop now groups forms by `(connection_id, odk_project_id)` and
  reuses one pyODK client across every form in that group for delta checks,
  OData fetches, and attachment requests

## Canonical Payload Enrichment

Current sync writes remain OData-first, but selected operational metadata is
now enriched before payload fingerprinting and persistence.

Current canonical stored payload fields include:

- OData form-answer payload
- `FormVersion`
- `DeviceID`
- `SubmitterID`
- `instanceID`
- `ReviewState`
- `instanceName`
- `AttachmentsExpected`
- `AttachmentsPresent`

Current enrichment sources:

- submission XML:
  `FormVersion`, `DeviceID`
- submission metadata endpoint:
  `SubmitterID`, `instanceID`, and fallback review metadata
- attachments endpoint:
  `AttachmentsExpected`, `AttachmentsPresent`

NaN-like values are normalized to missing before persistence so downstream
consumers such as SmartVA do not receive stored `NaN` payload values.

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

### SmartVA input lineage

ODK sync no longer rebuilds a flat CSV for SmartVA. Instead:

- sync writes normalized submission content into `va_submissions`
- each submission also carries an active `VaSubmissionPayloadVersion`
- SmartVA prep reads from `VaSubmissionPayloadVersion.payload_data` for the pending `va_sid` set

This means incremental syncs do not need a form-wide CSV rebuild step. SmartVA input is derived directly from the active payload-version records for the submissions being processed.

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
- operational cleanup scripts may quarantine orphaned files under
  `media/.orphaned/` for inspection and rollback instead of deleting them
- `.orphaned` subtrees are excluded from active attachment integrity scans so
  quarantined files do not keep appearing as live orphaned media

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

`.amr` files are converted to `.mp3` using **SoX** immediately after download. The converter probes the source bitrate via `soxi` and targets 2x the source bitrate (capped 16–64 kbps) — AMR-NB speech at ~12 kbps produces 24 kbps MP3 output, optimal quality for the source without bloated file size. The `.amr` file is deleted after successful conversion. Conversion failure keeps the `.amr` on disk (better than data loss).

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
- Submission exists with changed `va_odk_updatedat` + protected state → metadata updated, transitions to `finalized_upstream_changed`
- Submission exists with changed `va_odk_updatedat` + non-protected state → updated; active workflow artifacts deactivated; consent re-evaluated to set new workflow state
- Submission does not exist → inserted unconditionally; consent evaluated to set initial workflow state

All submissions from ODK are stored regardless of consent value. Consent determines workflow routing:

| Consent value | Workflow state |
|---|---|
| Present and not `"no"` (e.g. `"yes"`, `"telephonic_consent"`) | `smartva_pending` in current runtime for newly synced or payload-changed submissions; desired target remains `smartva_pending` until SmartVA is generated, regenerated, or explicitly failed-and-recorded |
| `"no"` | `consent_refused` |
| Empty / missing | `consent_refused` |

When a non-protected submission is updated, the app deactivates related local workflow artifacts:

- Active coder allocations
- Coder review records
- Initial assessments
- Final assessments
- Reviewer reviews
- User notes

ODK is treated as the source of truth for submission content. See [ODK Sync Policy](../policy/odk-sync-policy.md).

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

- newly inserted consented submissions are initialized as
  `attachment_sync_pending`
- updated submissions refresh their canonical workflow row after local
  workflow artifacts are deactivated
- attachment completion transitions `attachment_sync_pending` submissions into
  `smartva_pending`
- SmartVA generation transitions `smartva_pending` submissions to
  `ready_for_coding` once results are saved
- active SmartVA projections are expected to align to the submission's current
  active payload version

Desired target behavior:

- consent-valid submissions should enter `attachment_sync_pending` first
- only after attachment syncing finishes should they become `smartva_pending`
- only after SmartVA is generated, regenerated, or explicitly failed-and-recorded,
  should the submission become `ready_for_coding`
- only new or changed payloads should pass through that gate
- same-payload cleanup returns do not require SmartVA rerun

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

Current upstream-review behavior:

- `Accept And Recode` promotes the pending upstream payload, deactivates the
  old SmartVA projection, and reruns SmartVA for the new payload
- `Keep Current ICD Decision` promotes the pending upstream payload but keeps
  the prior SmartVA interpretation by rebinding the preserved SmartVA
  projection to the newly active payload instead of regenerating it

Current implementation gap:

- explicit SmartVA-failure recording is not yet implemented
- so the failure-handled path from `smartva_pending` to `ready_for_coding`
  remains incomplete

## Sync Scheduling

Sync is driven by Celery beat using `celery-sqlalchemy-scheduler` DatabaseScheduler.

Tasks:

- [`run_odk_sync()`](../../app/tasks/sync_tasks.py) — full sync across all active forms; records outcome in `va_sync_runs`
- [`run_single_form_sync(form_id)`](../../app/tasks/sync_tasks.py) — force-resync one form, bypasses delta check
- [`run_single_submission_sync(va_sid)`](../../app/tasks/sync_tasks.py) — refreshes one local submission from ODK, then queues canonical current-payload repair for that submission

During gap rebuilds for forms with many missing local rows, both regular sync
and form backfill now queue canonical repair per fetched/upserted
missing-data batch rather than waiting for the entire form gap fill to finish
first.

Because canonical repair now owns the current-payload workflow handoff, these
incremental batches can also advance workflow earlier:

- `attachment_sync_pending -> smartva_pending` once attachments are complete
- `smartva_pending -> ready_for_coding` once current-payload SmartVA is present

Within each canonical repair batch, SmartVA now runs through the production
form-batch service path for the batch target SIDs instead of one
`generate_for_submission(...)` call per submission. That keeps the current
payload semantics the same while using SmartVA much more efficiently.

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

The sync dashboard also exposes a separate backfill coverage view and trigger:

- `GET /admin/api/sync/backfill-stats` returns project/site/form completeness counts for:
  - local stored submission totals
  - metadata completeness
  - attachment completeness
  - attachment row coverage split between current rows (`storage_name IS NOT NULL`) and legacy rows (`storage_name IS NULL`)
  - SmartVA completeness (`smartva_complete`)
  - SmartVA missing, failed/null, and no-consent detail counts (`smartva_missing`, `smartva_failed`, `smartva_no_consent`)
  - SmartVA missing excludes consent-refused rows (`va_consent = "no"`)
- `POST /admin/api/sync/backfill/form/<form_id>` triggers the ODK-backed repair path for one form
- `GET /admin/api/sync/legacy-attachment-stats` returns counts of
  `va_submission_attachments` rows where `storage_name IS NULL`, split between
  legacy media rows and intentionally skipped `audit.csv` rows, plus a derived
  count of already repaired legacy media rows
- `POST /admin/api/sync/legacy-attachment-repair` triggers a dedicated repair
  task that assigns deterministic opaque `storage_name` values to legacy
  non-`audit.csv` attachment rows and renames the local files accordingly
- The dashboard table groups rows by project, site, and form so operators can see which forms are missing local data, metadata, or attachments before triggering a repair
- In the Form Repair table, SmartVA displays complete-only counts in-cell; missing, failed/null, and no-consent counts are shown on hover
- The Legacy Attachment Rows card should normally show zero legacy media rows;
  nonzero values indicate renderability gaps that the general repair-coverage
  query will not surface on its own

Important distinction:

- `POST /admin/api/sync/form/<form_id>` is the force-resync path and bypasses the delta check for the whole form
- `POST /admin/api/sync/backfill/form/<form_id>` is the targeted repair path:
  - it fetches ODK instance IDs for the form
  - backfills only missing thin local submissions
  - then revalidates the current ODK payload for each repair candidate before
    ordinary metadata, attachment, or SmartVA repair continues
  - those ODK payload/comment fetches now use the configured connect/read
    request timeouts and the bounded repair stages currently run in batches of
    `5` submissions
  - ordinary repair still runs only for submissions with local gaps
  - protected submissions whose current ODK payload changed during that
    revalidation follow the existing `finalized_upstream_changed` /
    pending-upstream path and are held out of ordinary attachment and SmartVA
    repair against the stale active payload
  - attachment repair now also treats legacy attachment rows with `storage_name IS NULL` as incomplete and migrates them onto opaque storage names during the same run, even when the local file already exists
- the form backfill trigger can therefore repair thin data, metadata enrichment, attachment sync, legacy attachment-row migration, and SmartVA follow-through together without redownloading all form rows

## Admin Sync Dashboard

Available at Admin Console → Data Sync (admin-only).

Sections:

- **Status bar** — last run outcome; auto-refreshes every 30s (5s while running)
- **Sync** — manual routine sync trigger; 409 guard against concurrent runs
- **Stop** — shown only while a sync run is active; sends a revoke/terminate signal to the active Celery sync task and marks the run `cancelled`
- **Schedule configurator** — change beat interval (1–168h) without restarting
- **Coverage table** — ODK total vs local total, last synced time, per-form `Force-resync` button; loaded on demand rather than automatically on panel load
- **Form Repair coverage table** — project/site/form completeness counts for local data, metadata, attachments, and SmartVA, with a per-form `Repair` trigger; the attachments cell also shows current-vs-legacy attachment row coverage
- **Legacy Attachment Rows** — status card for `storage_name IS NULL` rows,
  repaired legacy media row totals, plus a dedicated `Repair` trigger for
  legacy media rows
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
