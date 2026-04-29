---
title: ODK Repair Workflow
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-29
---

# ODK Repair Workflow

This document describes the repair paths that bring DigitVA's local
current-payload state back into alignment with ODK without doing a full
force-resync.

It complements:

- [ODK Sync And Attachments](odk-sync.md)
- [ODK Sync Policy](../policy/odk-sync-policy.md)
- [Workflow And Permissions](workflow-and-permissions.md)

## Scope

The repair workflow is for **local completeness repair** after a submission row
already exists in DigitVA.

It covers:

- metadata enrichment for the current active payload
- attachment download or attachment-row migration for the current payload
- SmartVA generation for the current active payload when missing

It does **not** replace the main sync pipeline, and it does **not** silently
override protected finalized workflow states.

## Repair entrypoints

Current repair entrypoints are:

1. form-scoped `Backfill` from the admin sync dashboard
2. admin legacy-attachment repair for submissions still carrying legacy
   `storage_name IS NULL` rows
3. CLI payload backfill / enrich flows
4. Celery-queued single-submission repair when a coder or data manager opens a
   submission and the current payload still has local gaps

All four follow the same current-payload repair semantics.

The current simplification goal is:

- one shared per-submission current-payload repair engine
- multiple entrypoints that choose which submissions to send into that engine

Today that shared per-submission engine is:

- [`repair_submission_current_payload(...)`](../../app/services/open_submission_repair_service.py)
- [`run_canonical_repair_batches_task(...)`](../../app/tasks/sync_tasks.py)
  is the async wrapper used when a sync entrypoint needs to fan out the same
  canonical repair logic across many submissions

This function should be treated as the **canonical repair engine** for
per-submission repair. New repair entrypoints should reuse it unless there is a
clear reason they must operate at a different orchestration layer.

### Concrete routes and commands

Admin dashboard repair routes:

- `GET /admin/?panel=/admin/panels/sync`
  sync dashboard UI
- `GET /admin/api/sync/backfill-stats`
  form repair coverage telemetry
- `POST /admin/api/sync/backfill/form/<form_id>`
  form-scoped ODK-backed repair
- `GET /admin/api/sync/legacy-attachment-stats`
  legacy attachment migration telemetry
- `POST /admin/api/sync/legacy-attachment-repair`
  dedicated legacy attachment migration trigger, now routed through the same
  canonical repair engine per submission

Related force-resync routes, for contrast:

- `POST /admin/api/sync/form/<form_id>`
  full form force-resync
- `POST /admin/api/sync/project-site/<project_id>/<site_id>`
  ensure runtime form, then force-resync it

These force-resync routes now converge on the same canonical repair semantics
after ODK upsert by queueing `run_canonical_repair_batches_task(...)`.

For large gap-rebuild forms, regular sync also now pipelines this handoff per
fetched missing-data batch so enrichment/attachment/SmartVA repair can start
before the entire form's missing-data fetch completes.

CLI repair commands:

- `docker compose exec minerva_app_service uv run flask payload-backfill status`
- `docker compose exec minerva_app_service uv run flask payload-backfill enrich`
- `docker compose exec minerva_app_service uv run flask payload-backfill enrich --form-id=<form_id>`

Only `payload-backfill enrich` remains as the CLI repair entrypoint.

Page-open on-demand entrypoints:

- `POST /coding/start`
- `GET /coding/resume`
- `POST /coding/pick/<va_sid>`
- `POST /coding/demo`
- `GET /coding/view/<va_sid>`
- `GET /data-management/view/<va_sid>`

These entrypoints eventually render through:

- [`render_va_coding_page(...)`](../../app/services/coding_service.py)

That shared shell now queues:

- [`run_open_submission_repair(...)`](../../app/tasks/sync_tasks.py)

for `va_action="vacode"` and `va_action="vadata"`.

## Core rule

Repair always operates against the **currently relevant ODK payload**, not just
whatever active payload DigitVA happened to store earlier.

That means repair must:

1. revalidate the current ODK payload for the submission
2. update or enrich the local active payload when allowed
3. stop ordinary repair if the submission transitions into
   `finalized_upstream_changed`

Only after payload revalidation may attachment or SmartVA repair continue.

## Form backfill repair path

Form backfill is a bounded, stage-aware orchestration layer over the canonical
per-submission repair engine.

High-level order:

1. resolve candidate submissions for the selected form
2. fetch missing thin local rows in batches of `50`
3. upsert each fetched batch locally
4. immediately queue canonical repair for that fetched batch
5. after the gap-fetch pass, build a repair map from any remaining local
   current-payload gaps
6. split remaining candidates into bounded repair batches
7. for each submission in each repair batch:
   - revalidate current ODK payload
   - enrich local current payload
   - rebuild repair needs from the refreshed local state
   - if still needed, sync attachments
   - if attachments are now complete for the current payload, advance
     `attachment_sync_pending -> smartva_pending`
   - collect any remaining SmartVA gaps across that repair batch
   - run SmartVA once per form for those batch target SIDs
   - if current-payload SmartVA is now present, advance
     `smartva_pending -> ready_for_coding`

The current batch sizes are:

- missing-thin-row fetch batches: `50`
- enrichment batches: `5`
- attachment batches: `5`

This smaller batch size is intentional because payload revalidation currently
uses one ODK request per submission.

The canonical repair engine now owns the current-payload workflow handoff too:

- sync/upsert still routes newly synced submissions into
  `attachment_sync_pending`
- canonical repair moves them to `smartva_pending` once current-payload
  attachments are complete
- canonical repair or SmartVA generation then moves them to
  `ready_for_coding` once current-payload SmartVA is present

## Legacy attachment repair

Legacy attachment repair is now a candidate-selection wrapper around the same
canonical repair engine.

High-level order:

1. find submissions with ODK-backed attachment rows where `storage_name IS NULL`
2. batch those submission IDs
3. run the canonical per-submission repair engine for each candidate
4. let ordinary attachment repair migrate the legacy rows onto opaque storage

This keeps legacy migration aligned with the same payload revalidation,
attachment-repair, and protection semantics as form backfill and on-open
repair.

## Single-submission on-open repair

When a coder or data manager opens a submission shell page, DigitVA may queue a
single-submission repair task before or during page rendering.

This is triggered only when the local current payload has a repair gap for that
submission.

Current gap checks are:

- metadata incomplete for the current active payload
- non-audit or audit attachments missing locally
- legacy attachment rows still need migration to opaque `storage_name`
- current-payload SmartVA missing

If there is no gap, the queued task no-ops.

If there is a gap, the Celery task runs the same stage order as batch repair,
but scoped to one submission:

1. load local current-payload state for the submission
2. fetch current ODK payload for that submission
3. enrich/update local current payload
4. rebuild local repair need from the refreshed state
5. if attachments are still incomplete, sync that submission's attachments
6. rebuild local repair need again
7. if current-payload SmartVA is still missing, generate SmartVA for that
   submission

This keeps coder-open and data-manager-open repair aligned with the admin/CLI
repair behavior instead of introducing a second custom repair implementation.

## Attachment repair semantics

Attachment repair is complete only when both are true:

- all expected current-payload attachments are present locally
- no legacy attachment rows remain for those ODK-backed files

Legacy attachment rows are rows where:

- `exists_on_odk = true`
- `storage_name IS NULL`

Those rows are not considered fully repaired just because a local file exists.
They remain part of the repair backlog until migrated to opaque storage names.

### Audit vs non-audit attachments

The repair UI now distinguishes:

- `Attachments`
  non-`audit.csv` files present / expected
- `Audit`
  current opaque audit files present / expected
- `Legacy`
  attachment records still requiring migration

Batch logs also report downloaded counts separately for:

- non-audit attachments
- `audit.csv`

## Repair coverage computation

The Form Repair Coverage table (`GET /admin/api/sync/backfill-stats`) is
local-only (no ODK calls) and loads automatically on panel load.

### Per-category completeness logic

| Category | Complete When | Missing Count |
|----------|--------------|---------------|
| **Local Data** | Always shown as total count | N/A |
| **Metadata** | All 8 fields present: `va_summary`, `va_category_list`, `FormVersion`, `DeviceID`, `SubmitterID`, `instanceID`, `AttachmentsExpected`, `AttachmentsPresent` | `local_total - metadata_complete` |
| **Attachments** (non-audit) | `present_file_count >= AttachmentsExpected` AND `legacy_count == 0`. `audit.csv` excluded from file count. | `expected - present` |
| **Audit** | `audit.csv` present on disk | `audit_expected - audit_present` (informational only, does NOT gate completeness) |
| **Legacy** | `storage_name IS NOT NULL` on all `exists_on_odk=true` attachment rows | Rows where `storage_name IS NULL` |
| **SmartVA** | Active `va_smartva_results` row exists for `active_payload_version_id` with non-empty `cause1` | `eligible - complete - failed` |

### What counts as a present attachment file

File resolution order per `va_submission_attachments` row:

1. `APP_DATA/<form_id>/media/<storage_name>` if `storage_name` is set
2. `local_path` fallback if `storage_name` is NULL
3. **Excluded**: `audit.csv` is never counted as a present file for repair-map completeness (it is shown separately in the UI for informational purposes)

Legacy rows (`storage_name IS NULL`) are flagged as incomplete even if the file
exists at the legacy `local_path`, because they need migration to opaque storage
names.

## Per-submission repair execution and save points

When the canonical repair engine processes one submission
(`repair_submission_current_payload`), it follows this sequence:

### Step 1: Build repair map

Calls `_build_repair_map_for_form` scoped to the single submission. If no gaps
(metadata, attachments, SmartVA), returns early with `{"reason": "no-gaps"}`.

### Step 2: Metadata enrichment

1. Fetches current ODK payload by instance ID (one ODK API call)
2. Enriches the local active payload with metadata fields
3. Updates `va_submission_payload_versions.payload_data` and `has_required_metadata`
4. Updates `va_submissions.va_summary` and `va_category_list`
5. **`db.session.commit()`** — saves enriched payload

### Step 3: Re-check after enrichment

Calls `_refresh_batch_plan_after_enrichment` to re-evaluate repair needs. If
the ODK payload changed and the submission is in a protected finalized state,
transitions to `finalized_upstream_changed` and **stops** — no attachment or
SmartVA repair proceeds.

### Step 4: Attachment repair

If `needs_attachments` is still true:

1. Creates `APP_DATA/<form_id>/media/` directory
2. Downloads ALL attachments from ODK (including `audit.csv`)
3. Migrates legacy rows to opaque `storage_name`
4. **`db.session.commit()`** — saves attachment rows and files

### Step 5: Workflow advancement

If attachments are now complete for the current payload:

- `attachment_sync_pending` → `smartva_pending`
- **`db.session.commit()`** — saves workflow state + audit log entry

### Step 6: SmartVA (batched separately)

In batch repair (`_run_canonical_repair_batches`), SmartVA is deferred per
submission (`run_smartva=False`). After each batch of 5 submissions, all SIDs
needing SmartVA are collected by form and run in one `smartva_service.generate_for_form()` call:

1. Prepares one CSV input for all target SIDs in that form
2. Runs SmartVA once (processes adult, child, neonate age groups)
3. Saves `va_smartva_form_runs` (form-level run metadata + disk path)
4. Saves `va_smartva_runs` (per-submission attempt history)
5. Saves `va_smartva_run_outputs` (raw likelihood rows as JSONB)
6. Saves `va_smartva_results` (active projection: cause1-3, likelihoods, ICD codes)
7. Copies workspace to disk under `APP_SMARTVA_RUNS/{project}/{form}/{run_id}/`
8. **`db.session.commit()`**

In single-submission on-open repair, SmartVA runs immediately via
`generate_for_submission` instead of being batched.

## Protected submissions

If payload revalidation detects a newer ODK payload for a protected finalized
submission, ordinary repair must stop.

Current behavior:

- the submission follows the existing `finalized_upstream_changed` path
- ordinary attachment repair is held back
- ordinary SmartVA repair is held back
- the protected active payload remains protected

This prevents repair from silently continuing on a stale finalized payload.

## SmartVA repair semantics

SmartVA repair is current-payload-aware.

The repair path checks whether the submission already has an active SmartVA row
for the current `active_payload_version_id`.

If current-payload SmartVA is missing:

- eligible non-protected submissions may generate SmartVA
- protected submissions continue to respect SmartVA protection rules

Single-submission on-open repair uses `generate_for_submission(...)` with a
distinct trigger source:

- `coding_open_repair`

CLI `payload-backfill enrich` also now reuses the same per-submission repair
engine, but with its own trigger source:

- `payload_backfill_enrich`

## Transactions and remote I/O

Repair deliberately releases ORM read transactions before remote ODK calls.

This avoids the earlier failure mode where a PostgreSQL session sat
idle-in-transaction while waiting on long ODK requests and was terminated by
Postgres timeout settings.

Current safeguards:

- ORM read transaction released before ODK fetches
- explicit ODK connect/read timeouts
- bounded batch sizes

## Request-path tradeoff

Single-submission on-open repair increases request latency when a submission has
real gaps, because DigitVA may need to:

- fetch the current ODK payload
- download missing attachments
- run SmartVA

But this behavior is intentionally gap-gated:

- if the current payload is already locally complete, no repair work runs

This makes the request-path repair a targeted safety net rather than a new
always-on sync path.

## Canonical repair iteration flow

```
Form Repair Coverage "Repair" button
    │
    ▼
POST /admin/api/sync/backfill/form/<form_id>
    │ queues Celery task
    ▼
run_single_form_backfill(form_id)
    │
    ├── 1. Fetch ODK instance IDs for this form
    ├── 2. Find missing thin local rows → upsert in batches of 50
    ├── 3. Build repair map for ALL local submissions
    └── 4. If any gaps → queue _run_canonical_repair_batches()
            │
            ▼
        _run_canonical_repair_batches()
            │ Split SIDs into batches of 5
            │ FOR EACH batch → FOR EACH va_sid:
            │   └── repair_submission_current_payload(va_sid)
            │       ├── a. Build repair map (no gaps → early return)
            │       ├── b. METADATA REPAIR → db.session.commit()
            │       ├── c. If upstream changed → STOP
            │       ├── d. ATTACHMENT REPAIR → db.session.commit()
            │       ├── e. WORKFLOW ADVANCEMENT → db.session.commit()
            │       └── f. SmartVA collected, batched per form
            └── Per form: smartva_service.generate_for_form() → commit
```

## Dedicated implementation links

Shared repair-planning and stage helpers:

- [`_build_repair_map_for_form(...)`](../../app/tasks/sync_tasks.py)
- [`_refresh_batch_plan_after_enrichment(...)`](../../app/tasks/sync_tasks.py)

Single-submission on-open repair service:

- [`repair_submission_for_coding_open(...)`](../../app/services/open_submission_repair_service.py)

Shared coding render path:

- [`render_va_coding_page(...)`](../../app/services/coding_service.py)

Attachment repair primitives:

- [`va_odk_sync_form_attachments(...)`](../../app/utils/va_odk/va_odk_07_syncattachments.py)
- [`va_odk_sync_submission_attachments(...)`](../../app/utils/va_odk/va_odk_07_syncattachments.py)

SmartVA repair primitive:

- [`generate_for_submission(...)`](../../app/services/smartva_service.py)
