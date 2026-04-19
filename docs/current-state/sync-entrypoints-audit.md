---
title: Sync Entrypoints Audit
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-19
---

# Sync Entrypoints Audit

## Scope

This audit maps current ODK-related sync buttons to their exact frontend and
backend execution paths for:

- Admin Sync panel: `/admin/?panel=%2Fadmin%2Fpanels%2Fsync`
- Data Management dashboard: `/data-management`

It also separates true ODK sync actions from read-only refresh actions.

## Entry Surface Map

### Admin Panel: Data Sync (`/admin/panels/sync`)

| UI button | Frontend call | Flask endpoint | Backend task/service path | Actual behavior |
|---|---|---|---|---|
| `Sync` | `apiJson('/admin/api/sync/trigger', 'POST')` | `POST /admin/api/sync/trigger` (`admin_sync_trigger`) | `run_odk_sync.delay(triggered_by='manual')` → `va_data_sync_odkcentral()` → `run_canonical_repair_batches_task.delay(...)` | Global sync run across active site mappings. Uses delta check + gap detection + thin upsert, then queues canonical current-payload repair for changed submissions. |
| `Stop` | `apiJson('/admin/api/sync/stop', 'POST')` | `POST /admin/api/sync/stop` (`admin_sync_stop`) | Celery revoke for known sync/backfill tasks | Attempts to terminate active sync/backfill tasks and marks running rows cancelled. |
| Coverage row refresh icon (form) | `syncForm(formId)` | `POST /admin/api/sync/form/<form_id>` (`admin_sync_form`) | `run_single_form_sync.delay(triggered_by='manual')` | Single-form force-resync; bypasses delta check and re-downloads all submissions for that form, then repair pipeline. |
| Coverage row refresh icon (site mapping without runtime form) | `syncProjectSite(projectId, siteId)` | `POST /admin/api/sync/project-site/<project_id>/<site_id>` (`admin_sync_project_site`) | `ensure_runtime_form_for_mapping()` + `run_single_form_sync.delay(...)` | Creates runtime form if needed, then runs same single-form force-resync path. |
| `Repair` (per-form in Form Repair Coverage table) | `apiJson('/admin/api/sync/backfill/form/<form_id>', 'POST')` | `POST /admin/api/sync/backfill/form/<form_id>` (`admin_sync_backfill_form`) | `run_single_form_backfill.delay(triggered_by='backfill')` | Local repair path for one form (missing thin rows / metadata / attachments / SmartVA). Now batches candidate submission IDs and runs the canonical per-submission repair engine for each. Not a full ODK force-resync of all records. |
| `Repair` (Legacy Attachment Rows card) | `apiJson('/admin/api/sync/legacy-attachment-repair', 'POST')` | `POST /admin/api/sync/legacy-attachment-repair` (`admin_sync_legacy_attachment_repair`) | `run_legacy_attachment_repair.delay(triggered_by='legacy-repair')` | Selects submissions still carrying legacy ODK-backed attachment rows, then routes them through the same canonical per-submission repair engine used by other repair paths. |

### Data Manager (`/data-management`)

| UI button | Frontend call | Flask endpoint | Backend task/service path | Actual behavior |
|---|---|---|---|---|
| `Sync Latest Data` (opens modal only) | Opens modal + preview fetch | N/A for button open | N/A | No sync yet; only opens scoped sync modal. |
| Modal preview (projects/sites selection) | `jsonFetch('/api/v1/data-management/sync/preview', POST)` | `POST /api/v1/data-management/sync/preview` (`sync_preview`) | `dm_scoped_forms()` + ODK count/id probes | Read-only preview: local counts, ODK counts, missing candidates, delta candidates. No writes. |
| `Sync All` in modal | Loop: `POST /api/v1/data-management/forms/<form_id>/sync` | `POST /api/v1/data-management/forms/<form_id>/sync` (`sync_form`) | `run_single_form_sync.delay(triggered_by='data-manager')` | Per-form task dispatch. Uses same single-form force-resync task as admin per-form force-resync. |
| Submission refresh API (no table button) | `POST /api/v1/data-management/submissions/<sid>/sync` (manual/programmatic only) | `POST /api/v1/data-management/submissions/<va_sid>/sync` (`sync_submission`) | `run_single_submission_sync.delay(triggered_by='data-manager')` | Refreshes one submission from ODK, then queues canonical current-payload repair for that SID. Endpoint still exists even after AG Grid row button removal. |
| `Recent Sync Results` refresh icon | `jsonFetch('/api/v1/data-management/sync/runs')` | `GET /api/v1/data-management/sync/runs` (`sync_runs`) | Read from `va_sync_runs` | Read-only status/history refresh. |

## Non-Sync Buttons Commonly Confused With Sync

| UI button | Endpoint | What it does |
|---|---|---|
| Data Manager `Refresh Dashboard` | `POST /api/v1/analytics/mv/refresh` | Refreshes analytics materialized view and reloads dashboard cards/charts/table. Does not pull from ODK. |
| Admin `Load/Refresh` in Coverage/Form Repair Coverage/Revoked/History cards | Various `GET /admin/api/sync/*` endpoints | Read-only telemetry/status data refresh. No ODK writes/downloads triggered by these alone. |
| Admin `Refresh` in Legacy Attachment Rows card | `GET /admin/api/sync/legacy-attachment-stats` | Read-only legacy attachment status refresh, including repaired legacy media row totals. No file or DB mutation. |
| Admin `Save` under Auto-sync interval | `POST /admin/api/sync/schedule` | Updates periodic schedule config only. |

## Adjacent But Different "Sync" Surface

The Field Mapping area (`/admin/panels/field-mapping/sync`) is not submission
sync. It calls `odk_schema_sync_service` to preview/apply schema/choice mapping
changes:

- `POST /admin/panels/field-mapping/sync/preview`
- `POST /admin/panels/field-mapping/sync/apply`

This updates mapping metadata, not `va_submissions` ingestion.

## Current-State Consolidation Observations (for streamlining)

1. Admin global `Sync` and Data Manager `Sync All` do not use the same path.
`Sync` runs `run_odk_sync` (delta-aware global pipeline), while DM `Sync All`
dispatches `run_single_form_sync` per form (force-resync semantics).

2. `run_single_form_sync` is shared by:
- admin per-form force-resync
- admin project/site sync
- data-manager form sync

This means DM "latest data" currently behaves like repeated force-resync calls,
not like one scoped delta-aware sync run.

3. There are separate repair-oriented flows:
- `run_single_form_backfill` (local gap repair)

This is operationally valuable, but adds button-level complexity when mixed
with primary sync controls.

4. The UI uses the word "sync" for different intent classes:
- ingest from ODK
- SmartVA-only regeneration
- local backfill/repair
- status refresh

This naming overlap is a major source of operator confusion in current state.
