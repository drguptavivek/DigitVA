---
title: Incremental ODK Sync — OData Filter-Gated Per-Form Download
doc_type: planning
status: implemented
owner: engineering
last_updated: 2026-03-14
---

# Incremental ODK Sync — OData Filter-Gated Per-Form Download

## Problem

Every sync run downloads the **full CSV zip for every active form**, regardless of whether anything has changed. For a project with 6 forms and thousands of submissions this means:

- Multi-minute downloads on every scheduled or manual sync
- A single slow/large form blocks all subsequent forms in sequence
- No way to resync a single form without triggering a full run
- Edited submissions are invisible to the sync gate if only counts are compared

## Goal

1. **OData filter-gated download** — ask ODK "how many submissions changed since last sync?" before downloading anything. Skip the form if zero.
2. **Catches both new and edited submissions** — filter on `submissionDate OR updatedAt`, not just count.
3. **Per-form isolation** — a failing form does not roll back work done for earlier forms.
4. **Force-resync of a single form** — bypasses the delta check entirely.
5. **Visible per-form sync state** — `last_synced_at` surfaced in the admin dashboard.

## Non-Goals (this phase)

- Fetching only the changed submissions via OData JSON (would require rewriting the CSV-based preprocessing pipeline — future work).
- Changing the per-submission upsert logic (update-if-updatedAt-changed stays as-is).
- Changing the SmartVA phase structure.

---

## Why not count-only, and why not `get_table`?

**Count-only** misses edits: a submission deleted and a new one added in the same period leaves the count unchanged but data has drifted.

**`get_table` with `$select=__id,__system/updatedAt`** is not lightweight: ODK Central must deserialise all ~500 fields per submission server-side before projecting. For 1,000+ submission forms this is still a significant server-side operation.

**ODK Central OData `$filter`** (supported since v1.1) is the right tool. With `$top=0&$count=true` and a filter on `submissionDate` and `updatedAt`, the server evaluates only the predicate and returns a single integer. No data is serialised or transferred. This is as lightweight as it gets.

Supported filter fields relevant to sync:

| Metadata | OData field |
|---|---|
| Submission created | `__system/submissionDate` |
| Submission last edited | `__system/updatedAt` |

---

## Design

### 1. Schema — one column on `map_project_site_odk`

| Column | Type | Purpose |
|---|---|---|
| `last_synced_at` | `TIMESTAMP WITH TIME ZONE` nullable | Timestamp used in the last successful delta check. NULL = never synced → always download. |

Migration: additive, backward-compatible. One column, no data loss.

### 2. Delta check — `va_odk_05_deltacheck.py`

New utility function:

```python
def va_odk_delta_count(
    odk_project_id: int,
    odk_form_id: str,
    since: datetime,          # must be timezone-aware (UTC); serialised as full ISO 8601
    app_project_id: str | None = None,
) -> int:
    """Return count of submissions created or updated after `since`.

    Calls OData with:
      $filter=(__system/submissionDate gt 2026-03-14T06:56:35.000Z)
           or (__system/updatedAt gt 2026-03-14T06:56:35.000Z)
      &$top=0&$count=true

    `since` MUST be a full datetime with timezone — never a date-only value.
    ODK treats bare dates as midnight UTC, silently missing same-day submissions.

    Returns @odata.count. ODK server evaluates only the filter predicate —
    no submission data is serialised or transferred.
    """
```

Timeout-guarded (same pattern as `va_odk_submissioncount`). On ODK error → raises, caller treats as "unknown" and falls through to full download.

**Datetime precision**: ODK `submissionDate` and `updatedAt` include a full time component. The `since` value passed to the filter must be a full ISO 8601 datetime with timezone (e.g. `2026-03-14T06:56:35.000Z`), never a date-only string. A bare date like `2026-03-14` is treated as `2026-03-14T00:00:00Z` by ODK — submissions from later that same day would be missed. Always use `datetime` objects with UTC tzinfo, serialised as `strftime("%Y-%m-%dT%H:%M:%S.000Z")`.

### 3. Sync loop — check → decide → download

```
snapshot_time = now()   # capture before any ODK calls

For each active form:
  a. If mapping.last_synced_at is NULL:
       → first-ever sync, skip check, download
  b. Else:
       → delta = va_odk_delta_count(since=mapping.last_synced_at)
       → if delta == 0:
            log "[ICMR01RJ0101] up to date, skipping"
            continue
  c. Download full CSV zip (existing logic unchanged)
  d. Upsert submissions (existing logic unchanged)
  e. db.session.commit()   ← per-form commit
  f. mapping.last_synced_at = snapshot_time
     db.session.commit()
```

`snapshot_time` is fixed at the start of the run. Using it (rather than wall clock after success) ensures that any submission arriving during the download is caught on the next sync rather than silently skipped.

### 4. Per-form isolation

The existing single transaction covering all forms becomes **one commit per form**. A download or upsert failure on one form:
- Is logged with full traceback
- Does not roll back already-committed earlier forms
- Does not update `last_synced_at` for the failed form (so it retries next run)
- Marks the overall sync run as `partial` (new status — see §6)

### 5. Single-form force-resync

**New Celery task:**

```python
@shared_task(name="app.tasks.sync_tasks.run_single_form_sync")
def run_single_form_sync(form_id: str, triggered_by: str = "manual"):
    """Download and upsert a single form, bypassing the delta check."""
```

**New admin API endpoint:**

```
POST /admin/api/sync/form/<form_id>
```

Requires `admin` role. Triggers `run_single_form_sync.delay(form_id)`.

**Admin UI:** Per-row sync icon button in the SmartVA Coverage table. Disables while running.

### 6. Sync run status — add `partial`

`va_sync_runs.status` currently allows `running`, `success`, `error`.

Add `partial`: one or more forms failed but at least one succeeded. The error message lists the failed form IDs.

| Outcome | Status |
|---|---|
| All forms succeeded (or skipped) | `success` |
| At least one succeeded, at least one failed | `partial` |
| All forms failed / task crashed | `error` |

### 7. Progress log format

```
[ICMR01RJ0101] delta check: 0 changes since 2026-03-14T06:56:35Z — skipped
[UNSW01KA0101] delta check: 6 changes since 2026-03-14T06:56:35Z — downloading…
[UNSW01KA0101] done: +6 added, 0 updated
[UNSW01NC0101] delta check failed (ODK timeout) — downloading as fallback
```

---

## Affected Files

| File | Change |
|---|---|
| `app/models/map_project_site_odk.py` | Add `last_synced_at` (nullable timezone-aware timestamp) |
| `migrations/` | One additive idempotent migration |
| `app/utils/va_odk/va_odk_05_deltacheck.py` | New: `va_odk_delta_count()` |
| `app/services/va_data_sync/va_data_sync_01_odkcentral.py` | Add delta check before download, per-form commit, partial status handling |
| `app/tasks/sync_tasks.py` | Add `run_single_form_sync` task; handle `partial` status in `run_odk_sync` |
| `app/routes/admin.py` | Add `POST /admin/api/sync/form/<form_id>` |
| `app/templates/admin/panels/sync_dashboard.html` | Per-form sync button; surface `last_synced_at` per form |

---

## Implementation Sequence

1. Schema migration — add `last_synced_at` to `map_project_site_odk`.
2. `va_odk_05_deltacheck.py` — implement and unit-test the OData filter call in isolation.
3. Refactor `va_data_sync_01_odkcentral.py` — add delta check + per-form commit. No skip logic yet (delta count > 0 always). Verify per-form commit works correctly.
4. Add skip logic — wire in `last_synced_at` update on success; skip when delta == 0.
5. Add `partial` status to sync run recording.
6. Add `run_single_form_sync` task + admin API + UI button.
7. End-to-end test (see checklist below).

## Verification Checklist

- [ ] Second sync run: all unchanged forms show "skipped", `last_synced_at` updated
- [ ] New ODK submission added: only that form downloads on next sync
- [ ] Edited ODK submission: caught by `updatedAt` filter, form downloads
- [ ] Force-resync single form: bypasses delta check, downloads regardless
- [ ] ODK delta check timeout: form falls through to full download, sync continues
- [ ] One form download failure: earlier forms committed, failed form retries next run, status = `partial`
- [ ] First-ever sync (NULL `last_synced_at`): always downloads
- [ ] No regression: upsert / SmartVA / allocation-release logic unchanged

## Phase 2 — Per-Submission Attachment Download (replace CSV ZIP)

### The current waste

`va_odk_downloadformdata` does this on every sync, for every form:

```python
shutil.rmtree(va_formdir)        # wipes entire local directory — all attachments deleted
...
zip_response = client.get("submissions.csv.zip")   # downloads CSV + ALL attachments
zip_ref.extractall(va_formdir)   # re-writes every file
# then converts every .amr → .mp3 from scratch (skip-if-newer check is useless
# because rmtree already deleted the .mp3s)
```

The `.amr → .mp3` skip check (`if os.path.exists(mp3_path) and mtime(mp3) > mtime(amr)`) is dead code — `rmtree` runs before it and deletes all converted files. Every sync reconverts every audio file from scratch.

**Each VA submission carries a variable number of attachments:**
- **Narration audio** — typically one `.amr` file per submission, requires `.amr → .mp3` conversion
- **Photos/images** — variable count per submission (0 to many); no conversion, store as-is
- Other media (e.g. audit logs) may also be present

The ZIP bundles every attachment across every submission. Total ZIP size is therefore `O(submissions × avg_attachments_per_submission)` and grows unboundedly as new submissions accumulate. A form with 1,155 submissions each carrying 1 audio + 3 images is downloading and extracting 4× 1,155 = ~4,620 files on every sync run.

### What Phase 2 replaces this with

ODK Central attachment API:

```
GET /v1/projects/{id}/forms/{formId}/submissions/{instanceId}/attachments
→ [{name: "audio.amr", exists: true}, ...]   (cheap — no binary)

GET /v1/projects/{id}/forms/{formId}/submissions/{instanceId}/attachments/{filename}
Headers: If-None-Match: <stored_etag>
→ 304 Not Modified  (if unchanged — zero bytes transferred)
→ 200 + binary      (if changed — download only this file)
```

### Phase 2 flow

```
For each changed submission (from delta check):
  1. Fetch submission data via OData JSON (no ZIP, no attachments)
  2. Fetch attachment list for this instanceId
  3. For each attachment where exists=true:
       a. Check local ETag store → If-None-Match header
       b. 304 → skip; 200 → write file + store new ETag
       c. If file is `.amr` → convert to `.mp3`, delete `.amr`
       d. If file is an image → store as-is (no conversion)

For submissions that are NOT in the changed set:
  → skip entirely (data already in DB, files already on disk)
```

**Do NOT `rmtree` the form directory.** Keep existing files. Only write new/changed ones.

**Why `rmtree` is harmful beyond performance**: The rendering pipeline (`va_render_06_processcategorydata`) checks `os.path.exists(data/<form_id>/media/<file>)` to decide whether to render an attachment field. If the file is missing, the field is silently dropped from the coder's view. Currently, every sync wipes `media/` and then re-downloads — creating a window (seconds to minutes depending on form size) where all attachment fields disappear for any coder actively working on a submission. Eliminating `rmtree` closes this gap entirely.

### Net result

For a routine sync where 5 new submissions arrive out of 1,155:
- Phase 1 (delta check): one OData count call — confirms 5 changes
- Phase 2: 5 attachment lists fetched + ~5 audio files downloaded + ~5 `.amr → .mp3` conversions
- 1,150 submissions: zero network, zero disk writes, zero conversions

### Why deferred to Phase 2

Requires replacing the CSV ZIP + pandas pipeline with OData JSON parsing — a rewrite of `va_odk_02_downloadformdata.py` and `va_preprocess_01_prepdata.py`. Phase 1 (delta check + skip unchanged forms entirely) delivers the majority of the benefit with minimal code change and regression risk.

### Local ETag storage

New table `va_submission_attachments`:

| Column | Type | Purpose |
|---|---|---|
| `va_sid` | FK → `va_submissions.va_sid` | Submission |
| `filename` | VARCHAR(255) | Original filename from ODK (e.g. `audio.amr`, `photo1.jpg`) |
| `local_path` | VARCHAR(512) | Actual path on disk (may differ — `.amr` stored as `.mp3`) |
| `mime_type` | VARCHAR(64) | Detected MIME type (`audio/mpeg`, `image/jpeg`, etc.) |
| `etag` | VARCHAR(128) | Last ETag from ODK for conditional re-download |
| `exists_on_odk` | BOOLEAN | Whether ODK has the file (`exists` flag from listing API) |
| `last_downloaded_at` | TIMESTAMP WITH TIME ZONE | When last fetched from ODK |

Primary key: `(va_sid, filename)`.

**Variable attachment count is handled naturally** — one row per `(submission, file)` pair. A submission with 1 audio + 4 images gets 5 rows; a submission with only audio gets 1 row. No schema change needed as attachment counts vary across submissions or change over time.

---

## Risks

| Risk | Mitigation |
|---|---|
| ODK Central < v1.1 (no `$filter` support) | Detect HTTP 501/400 from ODK → fall through to full download; log warning |
| `snapshot_time` clock skew between app and ODK server | Use ODK server time if available; otherwise accept a small window of re-download on next sync (safe, idempotent upsert handles duplicates) |
| Per-form commit exposes partial state mid-run | Each form's data is self-consistent; SmartVA runs after all forms complete |
| `last_synced_at` not updated on partial success | Intentional — failed forms always retry; no silent data loss |
