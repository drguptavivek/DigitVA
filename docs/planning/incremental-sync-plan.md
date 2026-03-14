---
title: Incremental ODK Sync — Per-Form Metadata-Gated Download
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-03-14
---

# Incremental ODK Sync — Per-Form Metadata-Gated Download

## Problem

Every sync run downloads the **full CSV zip for every active form**, regardless of whether anything has changed. For a project with 6 forms and thousands of submissions this means:

- Multi-minute downloads on every scheduled or manual sync
- A single slow/large form (e.g. a new site's first sync) blocks all subsequent forms
- No way to resync a single form without triggering a full run
- The existing lightweight ODK count endpoint (`$top=0&$count=true`) is unused for gating

## Goal

1. **Metadata-gated download** — check ODK submission count before downloading; skip if unchanged.
2. **Per-form isolation** — a slow or failing form does not block others.
3. **Force-resync of a single form** — via admin UI and API.
4. **Visible per-form sync state** — last synced time and count surfaced in the admin dashboard.

## Non-Goals

- ODK-side cursor / `$filter` incremental fetch (ODK Central does not expose reliable `since` cursors on the CSV export endpoint).
- Changing the per-submission upsert logic (update-if-updatedAt-changed stays as-is).
- Changing the SmartVA phase structure.

---

## Design

### 1. Schema — add sync state to `map_project_site_odk`

Add two nullable columns:

| Column | Type | Purpose |
|---|---|---|
| `last_synced_at` | `TIMESTAMP WITH TIME ZONE` nullable | When this form last completed a successful sync |
| `last_synced_submission_count` | `INTEGER` nullable | ODK submission count at last successful sync |

Migration: additive, fully backward-compatible. Existing rows get `NULL` for both (treated as "never synced" → always download on first run).

### 2. Sync loop — check → decide → download

Replace the current unconditional download loop with:

```
For each active form:
  a. Call ODK count API  →  odk_count   (cheap: $top=0&$count=true, ~100ms)
  b. Read  map_project_site_odk.last_synced_submission_count  →  known_count
  c. If odk_count == known_count AND force=False:
       → log "ICMR01RJ0101: up to date (N submissions), skipping download"
       → continue to next form
  d. Else:
       → download full CSV zip for this form only
       → upsert submissions (existing logic unchanged)
       → on success: update last_synced_at = now(), last_synced_submission_count = odk_count
```

**Note on count-only check**: count equality is a fast proxy. It will miss the case where one submission was deleted and another added (same count, different data). That is an acceptable trade-off for now; a force-resync covers the edge case.

### 3. Per-form sync isolation

Extract the per-form download + upsert into a standalone function:

```python
def sync_one_form(va_form, force=False, log_progress=None) -> dict:
    """Download and upsert submissions for a single form.
    Returns {"added": int, "updated": int, "discarded": int, "skipped": bool}
    """
```

The main `va_data_sync_odkcentral()` calls this in a loop. Each form is committed independently — a failure on one form does not roll back work already done for earlier forms.

### 4. Single-form force-resync

**New Celery task:**

```python
@shared_task(name="app.tasks.sync_tasks.run_single_form_sync")
def run_single_form_sync(form_id: str, triggered_by: str = "manual"):
    ...
```

**New admin API endpoint:**

```
POST /admin/api/sync/form/<form_id>
```

Triggers `run_single_form_sync.delay(form_id, triggered_by=current_user)`. Requires `admin` role.

**Admin UI:** Add a "Sync" icon button per row in the SmartVA Coverage table. Calls the above endpoint. Disables while running.

### 5. Sync run logging — per-form progress

The existing `va_sync_runs.progress_log` already records free-text progress. Per-form entries will use a consistent prefix:

```
[ICMR01RJ0101] up to date (42 submissions), skipped
[UNSW01KA0101] ODK count=256, local count=250 — downloading…
[UNSW01KA0101] done: +6 added, 0 updated
```

---

## Affected Files

| File | Change |
|---|---|
| `app/models/map_project_site_odk.py` | Add `last_synced_at`, `last_synced_submission_count` |
| `migrations/` | New Alembic migration for above columns |
| `app/services/va_data_sync/va_data_sync_01_odkcentral.py` | Refactor download loop to use `sync_one_form()`, add skip logic |
| `app/services/va_data_sync/va_data_sync_sync_one_form.py` | New file: `sync_one_form()` extracted logic |
| `app/tasks/sync_tasks.py` | Add `run_single_form_sync` task |
| `app/routes/admin.py` | Add `POST /admin/api/sync/form/<form_id>` |
| `app/templates/admin/panels/sync_dashboard.html` | Per-form sync button in coverage table |

---

## Migration Plan

1. Write and test Alembic migration (additive, no data loss).
2. Implement `sync_one_form()` — parity with existing logic first, then add skip logic.
3. Update `va_data_sync_odkcentral()` to call `sync_one_form()` in loop with commit-per-form.
4. Add `run_single_form_sync` task + admin API endpoint.
5. Add UI button.
6. Test: full sync (all forms skipped on second run), force-resync single form, new form first-ever sync.

## Verification Checklist

- [ ] Second sync run after a successful first run: all unchanged forms show "skipped"
- [ ] After a new ODK submission is added: only that form downloads on next sync
- [ ] Force-resync of single form via admin UI triggers only that form
- [ ] A form download failure does not prevent other forms from syncing
- [ ] `last_synced_at` and `last_synced_submission_count` updated correctly after each form
- [ ] Progress log entries appear correctly in admin dashboard per form
- [ ] No regression: existing upsert / SmartVA / allocation-release logic unchanged

## Risks

| Risk | Mitigation |
|---|---|
| Count match masks same-count data drift | Force-resync available; scheduled full sync can be forced periodically |
| Per-form commit changes transaction boundary | Test carefully for partial-sync scenarios; each form is independently recoverable |
| ODK count API unavailable | Treat count fetch failure as "unknown" → fall through to full download |
