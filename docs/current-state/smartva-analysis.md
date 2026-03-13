---
title: SmartVA Analysis
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-13
---

# SmartVA Analysis

SmartVA is an automated cause-of-death classification tool for Verbal Autopsy (VA) data. This document covers how DigitVA integrates SmartVA: input preparation, execution, output parsing, result storage, and operational considerations.

## Overview

SmartVA is run as a subprocess via a bundled x86-64 binary (`resource/smartva`). It consumes a CSV exported from ODK submissions and produces a multi-age-group cause-of-death ranking per submission. Results are stored in `va_smartva_results` and surfaced to coders in the VA coding interface.

SmartVA runs in **Phase 2** of the data sync pipeline, after ODK submissions have been downloaded and upserted (Phase 1). It can also be triggered independently via the admin dashboard "Gen SmartVA" button.

---

## Architecture

### Binary

| Property | Value |
|---|---|
| Path | `resource/smartva` |
| Architecture | x86-64 Linux (ELF) |
| Execution environment | `minerva_celery_worker` container (`platform: linux/amd64`) |
| Must NOT run in | `minerva_app_service` (aarch64 on ARM hosts — will fail) |

The binary must be executable on the host filesystem (not only inside the image). Because the repo is bind-mounted into the container, run:

```bash
chmod +x resource/smartva
```

on the host after checkout if the permission is lost.

### Containers

SmartVA is CPU-intensive and architecture-specific:

- **`minerva_celery_worker`** — `platform: linux/amd64` — runs SmartVA via Celery tasks
- **`minerva_app_service`** — `platform: linux/amd64` — required to match the bind-mounted `.venv` (which has x86-64 `.so` files)

Both services must be `linux/amd64` because the host `.venv` (bind-mounted at `/app/.venv`) contains x86-64 shared libraries (e.g. `pydantic_core._pydantic_core`).

---

## Data Flow

```
ODK CSV (on disk)
    │
    ▼
va_smartva_prepdata()         # filter columns, fix age, write smartva_input.csv
    │
    ▼
va_smartva_runsmartva()       # subprocess: ./resource/smartva smartva_input.csv
    │
    ▼
smartva_output/               # per-age-group result CSVs
    │
    ▼
va_smartva_formatsmartvaresult()   # parse output, join cause columns
    │
    ▼
va_smartva_appendsmartvaresults()  # load into DataFrame, resolve existing DB results
    │
    ▼
va_smartva_results (DB table)
```

---

## Input Preparation (`va_smartva_02_prepdata.py`)

### Source file

`{APP_DATA}/{form_id}/{odk_form_id}.csv` — the compiled ODK submission CSV produced by the download step.

### Column filtering

SmartVA requires **exactly** the standard WHO VA 2022 column set. Extra columns cause the header mapper to fail with:

```
Cannot process data without: gen_5_4*
```

Columns dropped before writing SmartVA input:

| Prefix | Reason |
|---|---|
| `sa01`–`sa19` | Social-autopsy modules (ICMR training forms) |
| `sa_` | Social-autopsy fields |
| `sa_note`, `sa_tu` | Social-autopsy variants |
| `survey_block` | Telephonic interview metadata |
| `telephonic_consent` | Telephonic interview metadata |

The filtered CSV is written to `{APP_DATA}/{form_id}/smartva_input/smartva_input.csv`.

### Age derivation

SmartVA derives `gen_5_4*` age-group flags from `ageInDays`. Some form versions (e.g. ICMR training forms where birth/death dates are unknown) record `finalAgeInYears` but leave `ageInDays` blank.

When `ageInDays` is empty and `finalAgeInYears` is present:

```python
ageInDays = round(float(finalAgeInYears) * 365)
```

### `nan` cleanup

Age columns (`ageInDays`, `ageInYears`, `ageInMonths`, etc.) may contain the string `"nan"` from pandas serialisation. These are replaced with `""` before writing.

### `sid` column

A `sid` column is appended to each row:

```
{KEY}-{form_id.lower()}
```

e.g. `uuid:abc123-icmr01nc0201`. This links SmartVA output rows back to submissions.

---

## Execution (`va_smartva_03_runsmartva.py`)

SmartVA is invoked as a subprocess:

```bash
./resource/smartva --country=Unknown \
    --hiv=False --malaria=False --hce=False \
    smartva_input.csv
```

Output is written to `{APP_DATA}/{form_id}/smartva_output/`.

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | SmartVA internal error (check stderr — often column/data issue) |
| 2 | Binary architecture mismatch (running x86-64 ELF in aarch64 container) |

If exit code ≠ 0, the function raises an exception that Phase 2 catches per-form, logs a warning, rolls back, and continues to the next form.

---

## Output Parsing (`va_smartva_04_formatsmartvaresult.py`)

SmartVA produces age-group-specific result CSVs under `smartva_output/`. The formatter merges them into a single DataFrame with columns:

| Column | Description |
|---|---|
| `sid` | Submission identifier |
| `age` | Estimated age at death |
| `sex` | Sex |
| `cause1` / `cause2` / `cause3` | Ranked cause-of-death labels |
| `likelihood1` / `likelihood2` / `likelihood3` | Likelihoods |
| `key_symptom1` / `key_symptom2` / `key_symptom3` | Key symptoms |
| `all_symptoms` | Full symptom list |
| `result_for` | Age group (adult/child/neonate) |
| `cause1_icd` / `cause2_icd` / `cause3_icd` | ICD-10 codes |

---

## Result Storage (`va_data_sync_01_odkcentral.py`)

Results are persisted in `va_smartva_results`. The save logic:

- **If submission was amended this sync run** (added or updated in Phase 1): deactivate any existing active result and write a new one.
- **If submission has no existing active result** (gap fill): write a new result regardless of whether it was amended.
- **If submission has an existing active result and was not amended**: skip (result is current).

This means every sync run — including SmartVA-only runs — fills in missing results without overwriting results for unchanged submissions.

Each saved result creates a `va_submissions_auditlog` entry. Each form's results are committed independently so a failure on one form does not roll back others.

---

## Celery Tasks (`sync_tasks.py`)

### `run_odk_sync`

Full sync: Phase 1 (download + upsert) followed by Phase 2 (SmartVA for all forms).

### `run_smartva_pending`

SmartVA-only: skips ODK download, runs Phase 2 only. Saves results for any submission without an active SmartVA result. Useful when:

- Data is already on disk and SmartVA failed mid-run
- New submissions were imported but SmartVA was skipped
- Manual re-run needed after fixing a SmartVA issue

Both tasks record to `va_sync_runs` with `triggered_by` set to `"manual"`, `"scheduled"`, or `"smartva-only"`.

---

## Admin Dashboard

The sync dashboard (`/admin/panels/sync`) exposes:

| Control | Description |
|---|---|
| **Sync Now** | Triggers `run_odk_sync` (full sync) |
| **Gen SmartVA** | Triggers `run_smartva_pending` (SmartVA only, no ODK download) |
| **SmartVA Results (Local)** card | Per-form coverage: submissions vs. results, pending count, progress bar |

API endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/admin/api/sync/trigger` | POST | Trigger full sync |
| `/admin/api/sync/trigger-smartva` | POST | Trigger SmartVA-only run |
| `/admin/api/sync/smartva-stats` | GET | Per-form SmartVA coverage counts |

---

## Operational Notes

### Stale "running" sync rows

If the Celery worker restarts mid-run, the `va_sync_runs` row stays `status='running'`. The `cleanup_stale_runs()` function marks rows older than 2 hours as `error` on worker startup. For faster failures, reset manually:

```sql
UPDATE va_sync_runs
SET status = 'error', finished_at = NOW(),
    error_message = 'Manually reset — worker restarted'
WHERE status = 'running';
```

### SmartVA binary permissions

If `resource/smartva` loses its executable bit (e.g. after a fresh checkout):

```bash
chmod +x resource/smartva
```

### ICMR training form specifics

The ICMR01NC0201 form uses a training variant with:
- 32 extra `sa*` social-autopsy columns (dropped by `va_smartva_prepdata`)
- Missing `ageInDays` for some records (derived from `finalAgeInYears * 365`)

Without these fixes, SmartVA fails with `Cannot process data without: gen_5_4*`.

### Re-running SmartVA without re-downloading

Use the **Gen SmartVA** button or trigger:

```bash
docker compose exec minerva_celery_worker uv run celery -A make_celery:celery_app call \
    app.tasks.sync_tasks.run_smartva_pending \
    --kwargs='{"triggered_by":"manual"}'
```

Or run directly in the worker container:

```python
from app import create_app
from app.services.va_data_sync.va_data_sync_01_odkcentral import va_smartva_run_pending
app = create_app()
with app.app_context():
    va_smartva_run_pending()
```
