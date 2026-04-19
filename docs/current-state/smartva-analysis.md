---
title: SmartVA Analysis
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-19
---

# SmartVA Analysis

SmartVA is an automated cause-of-death classification tool for Verbal Autopsy (VA) data. This document covers how DigitVA integrates SmartVA: input preparation, execution, output parsing, result storage, and operational considerations.

The SmartVA source code is available at `vendor/smartva-analyze` (git submodule, pinned to v3.0.0) for troubleshooting and reference.

## Workflow-State Guards

Current runtime behavior:

- SmartVA excludes protected workflow states during automatic generation:
  - `coder_finalized`
  - `reviewer_eligible`
  - `reviewer_finalized`
  - `finalized_upstream_changed`
  - `closed` if legacy rows exist
  - `consent_refused`
- new and payload-changed coding-eligible submissions are first routed to
  `smartva_pending`
- a successful SmartVA result transitions `smartva_pending -> ready_for_coding`
- a handled SmartVA failure also transitions
  `smartva_pending -> ready_for_coding`, but only after a durable failure row
  is recorded in `va_smartva_results`
- SmartVA readiness is now keyed to the current active payload version, not
  just to `va_sid`
- `va_smartva_results` now stores `payload_version_id`
- existing SmartVA rows were backfilled to the current
  `va_submissions.active_payload_version_id` during migration
- current runtime stores SmartVA in:
  - `va_smartva_form_runs` for form-level execution metadata and disk path
  - `va_smartva_runs` for durable per-submission attempt history
  - `va_smartva_run_outputs` for emitted per-run likelihood rows

Current protected-payload repair rule:

- SmartVA-only reprocessing may now repair protected finalized submissions whose current
  payload has no matching active SmartVA projection but already has preserved
  historical SmartVA
- in that case DigitVA rebinds the preserved SmartVA to the current payload
  instead of rerunning SmartVA
  - `va_smartva_results` for the active projection shown in the UI
- exact raw SmartVA-generated files may also be copied to disk under the
  configured `APP_SMARTVA_RUNS` base directory per form run for operational
  debugging
- `report.txt` rejection lines are now parsed, and submissions removed by
  SmartVA quality checks are recorded as `smartva_rejected` failures rather
  than generic missing-row failures

See [SmartVA Generation Policy](../policy/smartva-generation-policy.md) for the
policy baseline.

---

## Overview

SmartVA is run as a Python subprocess via the vendored `smartva` package
(`vendor/smartva-analyze`, git submodule, v3.0.0). It consumes a CSV exported
from ODK submissions and produces a multi-age-group cause-of-death ranking per
submission. Current runtime stores the active summary result in
`va_smartva_results` and surfaces that record to coders in the VA coding
interface.

Current lineage note:

- each active SmartVA row points to the payload version it was generated or
  failure-recorded for
- pending selection excludes a submission only when an active SmartVA row
  exists for the current active payload version
- an older active SmartVA row tied to a superseded payload version no longer
  satisfies the SmartVA gate for a newer payload
- the emitted raw likelihood row is persisted in `va_smartva_run_outputs`
- `va_smartva_results` acts as the current projection layer for the latest
  active run on the current payload version
- each `va_smartva_run` now links back to a `va_smartva_form_runs` row

SmartVA runs in **Phase 2** of the data sync pipeline, after ODK submissions have been downloaded and upserted (Phase 1). It may also run through current-payload repair entrypoints or worker-side invocation.

---

## Architecture

### SmartVA Package

| Property | Value |
|---|---|
| Source | `vendor/smartva-analyze` (git submodule, pinned to v3.0.0) |
| Install | uv path dependency (`[tool.uv.sources]` in `pyproject.toml`) |
| CLI entry point | `python -m smartva.va_cli` |
| Execution environment | `minerva_celery_worker` container |
| Required deps | `click`, `numpy`, `pandas`, `progressbar2`, `stemming`, `python-dateutil`, `xlsxwriter`, `matplotlib`, `colorama`, `pyparsing` (all via transitive deps) |

SmartVA runs natively as a Python module — no PyInstaller binary or `/tmp/_MEI*`
extraction overhead. It is installed as a uv path dependency, meaning `uv sync`
installs it from the local `vendor/smartva-analyze` directory. GUI-only
dependencies (`wxpython`, `tornado`) are excluded via
`[tool.uv] exclude-dependencies` in `pyproject.toml`.

### Containers

SmartVA runs inside the Celery worker. Since SmartVA is now pure Python (no
PyInstaller binary), it is architecture-independent and shares the same Python
interpreter as the worker process. Memory overhead is reduced by ~150-300MB
compared to the previous PyInstaller `--onefile` binary which extracted a
temporary runtime on each invocation.

- **`minerva_celery_worker`** — runs SmartVA via Celery tasks (batch size 10)
- **`minerva_app_service`** — runs tests and admin tasks; not used for production SmartVA

---

## How SmartVA Processes Input (Source-Level)

Understanding SmartVA's internals is essential for diagnosing prep failures. The pipeline inside SmartVA is:

```
smartva_input.csv
      │
      ▼
workerthread.py         # reads CSV, strips ODK path prefixes from headers,
                        # detects form type (WHO vs PHMRC)
      │
      ├─ WHO detected ──▶  who_prep.py    # maps Id10xxx columns → gen_5_* columns,
      │                                   # calculates gen_5_4a/b/c/d from age fields
      │
      └─ PHMRC fallback ─▶ (no age calc) ─▶ common_prep.py fails with gen_5_4* error
      │
      ▼
common_prep.py          # validates gen_5_4* exist, separates rows into
                        # adult / child / neonate matrices
      │
      ▼
{adult|child|neonate}_prep.py   # cause-of-death tariff scoring per age group
      │
      ▼
smartva_output/         # per-age-group result CSVs
```

### WHO Form Detection (the critical threshold)

`workerthread.py` determines form type by scanning headers after stripping ODK path prefixes:

- If **≥ 80% of headers match `Id\d+`** → treated as WHO questionnaire → `who_prep.py` runs → `gen_5_4*` computed
- If **< 80% match** → treated as PHMRC → no age conversion → `gen_5_4*` never created → `common_prep.py` fails

**This is why the ICMR `sa*` columns caused failures.** Those 32 extra columns diluted the `Id####` ratio below 80%, so SmartVA never recognised the form as WHO and never ran `who_prep.py`. Dropping them in `va_smartva_prepdata` was not cosmetic — it restored the detection threshold.

Any form integration that adds non-`Id####` columns risks this same failure if they push the ratio below 80%.

### Age Field Computation in `who_prep.py`

`who_prep.py::calculate_age()` tries each age source in priority order, stopping at the first non-empty value:

| Priority | Source columns | Output |
|---|---|---|
| 1 | `ageInYears`, `age_adult`, `age_child_years` | `gen_5_4a` (years), `agedays = years × 365` |
| 2 | `ageInMonths`, `age_child_months` | `gen_5_4b` (months), `agedays = months × 30` |
| 3 | `ageInDays`, `ageInDaysNeonate`, `age_neonate_days`, `age_child_days` | `gen_5_4c` (days) |
| 4 | `isAdult`, `isChild`, `isNeonate` (+ variants `1`, `2`) | `gen_5_4d` only (age group, no value) |
| 5 | nothing | `gen_5_4d = 9` (unknown) — `common_prep.py` will error |

Priority 4 is a degraded path: SmartVA knows the age module (adult/child/neonate) but not the actual age value. Causes are still scored but age-weighted precision is lost.

### Age Group Classification (in `common_prep.py`)

Once `gen_5_4*` is computed, rows are routed to age-group processors:

| Age group | Threshold |
|---|---|
| Neonate | ≤ 28 days |
| Child | 29 days – < 12 years |
| Adult | ≥ 12 years |

### The `gen_5_4*` Error Explained

`common_prep.py` line 98-99:

```python
missing_vars = [var for var in list(AGE_VARS.values()) if var not in headers]
status_logger.info('Cannot process data without: {}'.format(', '.join(missing_vars)))
```

This fires when `who_prep.py` was never run (PHMRC fallback) or ran but found no valid age fields at all. The error is always a symptom of one of:

1. WHO column ratio < 80% (extra non-`Id####` columns) — **fix: drop them in prepdata**
2. All age fields are blank/missing in the data — **fix: derive from `finalAgeInYears`**
3. Form is genuinely not WHO VA 2022 — **fix: do not run SmartVA on it**

---

## Data Flow (DigitVA)

```
active payload versions in DB
    │
    ▼
va_smartva_prepdata()
  - drop non-standard columns (sa*, survey_block, telephonic_consent)
  - replace "nan" strings with "" in age columns
  - derive ageInDays = round(finalAgeInYears × 365) when ageInDays is blank
  - synthesize age_neonate_days for date-derived neonates when needed
  - append sid = va_sid
  - write → temp workspace smartva_input.csv
    │
    ▼
va_smartva_runsmartva()       # subprocess: python -m smartva.va_cli smartva_input.csv smartva_output/
    │
    ▼
smartva_output/               # adult-predictions.csv, child-predictions.csv, neonate-predictions.csv
    │
    ▼
va_smartva_formatsmartvaresult()   # merge age-group CSVs, normalise columns
    │
    ▼
copy workspace to APP_SMARTVA_RUNS/{project_id}/{form_id}/{form_run_id}
    │
    ├─ likelihood rows → va_smartva_run_outputs
    ├─ per-submission attempts → va_smartva_runs
    └─ active projection → va_smartva_results
```

Current projection rule:

- `va_smartva_run_outputs` and `va_smartva_runs` are durable history
- `va_smartva_results` is the single active projection layer used by the app
- the active `va_smartva_results` row should match the submission's current
  active payload version
- when a payload changes and SmartVA is regenerated, older active projection
  rows must be deactivated
- when upstream review keeps the current ICD decision, the preserved SmartVA
  projection is rebound to the new active payload instead of being rerun
- the admin SmartVA repair path also rebinds preserved historical SmartVA for
  protected finalized submissions whose current payload would otherwise have no
  active SmartVA projection

---

## Input Preparation (`va_smartva_02_prepdata.py`)

### Source data

`VaSubmissionPayloadVersion.payload_data` for each submission's current active
payload version.

### Column filtering

Columns are dropped **before** writing SmartVA input to maintain the ≥80% `Id####` detection threshold:

| Prefix/name | Reason |
|---|---|
| `sa01`–`sa19` | Social-autopsy modules (ICMR training forms) |
| `sa_` | Social-autopsy generic fields |
| `sa_note`, `sa_tu` | Social-autopsy variants |
| `survey_block` | Telephonic interview metadata |
| `telephonic_consent` | Telephonic interview metadata |

The filtered CSV is written to the per-run temporary workspace as
`smartva_input.csv`, then copied into the persisted form-run disk path.

> Any future form integration that adds non-`Id####` columns should have those columns added to `_SMARTVA_DROP_PREFIXES` in `va_smartva_02_prepdata.py`.

### Age derivation

Some form versions (e.g. ICMR training forms where birth/death dates are unknown) record `finalAgeInYears` but leave `ageInDays` blank. `who_prep.py` tries `ageInDays` at priority 3 — if it is blank, it falls through to age-group flags only (priority 4, degraded).

To keep full age precision, prepdata derives `ageInDays` when missing:

```python
ageInDays = round(float(finalAgeInYears) * 365)
```

### `nan` cleanup

Age columns (`ageInDays`, `ageInYears`, `ageInMonths`, etc.) may contain the string `"nan"` from pandas serialisation. These are replaced with `""` before writing so SmartVA does not misparse them as numeric values.

### `sid` column

The `sid` column is set directly from the submission's `va_sid`.

e.g. `uuid:abc123-icmr01nc0201`. This links SmartVA output rows back to
submissions in `va_smartva_results`.

---

## Execution (`va_smartva_03_runsmartva.py`)

SmartVA is invoked as a Python subprocess:

```bash
python -m smartva.va_cli --country=Unknown \
    --figures=False --hiv=False --malaria=False --hce=True \
    smartva_input.csv smartva_output/
```

Output is first written to the temporary workspace, then the full workspace is
copied to:

`{APP_SMARTVA_RUNS}/{project_id}/{form_id}/{form_run_id}/`

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | SmartVA internal error — check stderr; usually a column/data validation issue |

If exit code ≠ 0, the exception is caught per-batch: the DB session is rolled
back, a warning is logged, and processing continues to the next batch. Batches
are processed in groups of `SMARTVA_BATCH_SIZE = 10` submissions per
invocation.

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
| `result_for` | Age group (adult / child / neonate) |
| `cause1_icd` / `cause2_icd` / `cause3_icd` | ICD-10 codes |

Current storage behavior:

- SmartVA emits age-group likelihood files under
  `smartva_output/4-monitoring-and-quality/intermediate-files/`
- DigitVA reads those files through the formatter, persists the emitted
  likelihood row for each submission run in `va_smartva_run_outputs`, and then
  projects the active summary into `va_smartva_results`
- the full raw SmartVA workspace may be copied once per form run to the
  persisted `disk_path` recorded in `va_smartva_form_runs` for operational
  debugging

---

## Result Storage (`va_data_sync_01_odkcentral.py`)

SmartVA attempts are persisted in `va_smartva_results`. The save logic per row:

| Condition | Action |
|---|---|
| Submission was amended this sync run (Phase 1 added/updated it) | Deactivate old result, write new one |
| Submission has no existing active result (gap fill) | Write new result regardless of Phase 1 |
| Submission has an existing active result and was not amended | Skip — result is current |
| SmartVA attempt fails for the current payload | Write an active failure row with `va_smartva_outcome = 'failed'` and failure metadata |

This means every sync run — including SmartVA-only runs — fills in missing results without overwriting results for unchanged submissions.

Current storage semantics:

- successful rows use `va_smartva_outcome = 'success'`
- failure rows use `va_smartva_outcome = 'failed'`
- both success and failure rows now carry `payload_version_id`
- failure rows also carry:
  - `va_smartva_failure_stage`
  - `va_smartva_failure_detail`
- SmartVA quality removals found in `report.txt` now use
  `va_smartva_failure_stage = 'smartva_rejected'`
- both success and failure rows follow the same active/inactive lifecycle, so a
  later payload change or successful rerun supersedes the old row cleanly

Current architectural behavior:

- `va_smartva_form_runs` stores form-level run metadata and disk path
- `va_smartva_results` now serves as the active projection layer
- durable run history is stored in `va_smartva_runs`
- emitted per-run likelihood rows are stored in `va_smartva_run_outputs`
- exact raw SmartVA files may also be stored on disk under the configured
  `APP_SMARTVA_RUNS` base directory at the form-run `disk_path`, but normal
  regeneration now derives from versioned payloads and persisted DB outputs
  rather than requiring preserved raw workspaces

Each saved result or failure record creates a `va_submissions_auditlog` entry.
Each form's results are committed independently so a failure on one form does
not roll back others.

---

## Mandatory Fields for SmartVA

When integrating a new ODK server or form, the following fields must be present in the ODK form schema. Missing fields at the wrong tier cause silent degradation or hard failures.

### Tier 1 — System mandatory (DigitVA won't function without these)

| Field | Source | Why mandatory |
|---|---|---|
| `KEY` | ODK submission metadata | Generates `sid` — primary key for every submission |
| `SubmissionDate` | ODK submission metadata | Submission timestamp |
| `SubmitterName` | ODK submission metadata | Data collector attribution |
| `Id10013` | WHO VA 2022 form | Consent gate — non-consented submissions are not imported |

### Tier 2 — SmartVA mandatory (cause-of-death analysis fails without these)

| Requirement | Acceptable fields | Notes |
|---|---|---|
| At least one age field | `ageInDays`, `ageInYears`, `ageInMonths`, `finalAgeInYears` | `finalAgeInYears` is a fallback — prepdata derives `ageInDays` from it |
| Sex | `Id10019` | Required for SmartVA scoring |
| WHO column ratio | ≥ 80% of form headers must match `Id\d+` after non-standard prefixes are dropped | Determines whether SmartVA runs `who_prep.py` or falls back to PHMRC |

### Tier 3 — Quality fields (warn if absent, do not block)

| Field | Impact if missing |
|---|---|
| `finalAgeInYears` | No fallback when `ageInDays` is blank — age degrades to group-only |
| `isAdult` / `isChild` / `isNeonate` | No age-group fallback if all numeric age fields are blank |
| `narr_language` / `language` | Narration language not tracked |
| `instanceName` | Display name unavailable |
| `unique_id` | Masked ID generation fails |
| `start` | Timestamp-based masked ID generation fails |

> A **Form Readiness Validator** that checks these tiers at ODK form mapping time — before any sync runs — is the correct long-term solution. See `docs/planning/` for the design proposal.

---

## Celery Tasks (`sync_tasks.py`)

### `run_odk_sync`

Full sync: Phase 1 (download + upsert) followed by Phase 2 (SmartVA for all forms).

These tasks record to `va_sync_runs` with `triggered_by` values such as `"manual"` or `"scheduled"`, depending on the initiating sync path.

---

## Admin Dashboard

The sync dashboard (`/admin/panels/sync`) exposes:

| Control | Description |
|---|---|
| **Sync Now** | Triggers `run_odk_sync` (full sync) |

API endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/admin/api/sync/trigger` | POST | Trigger full sync |

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

SmartVA runs as a Python module — no binary permissions to manage. The vendored
source is installed as a uv path dependency during Docker image build via
`uv sync`. To reinstall in a running container:

```bash
docker compose exec minerva_celery_worker bash -c \
    "cd /app && uv sync --frozen --no-dev"
```

### Diagnosing a new form failure

If SmartVA fails on a new form with `Cannot process data without: gen_5_4*`:

1. Inspect the generated input file:
   ```bash
   head -1 /app/smartva_runs/{project_id}/{form_id}/{form_run_id}/smartva_input.csv | tr ',' '\n' | grep -v 'Id[0-9]' | wc -l
   ```
   Count non-`Id####` headers. If this is high relative to total columns, the WHO detection threshold is being missed.

2. Check age fields are present:
   ```bash
   head -1 /app/smartva_runs/{project_id}/{form_id}/{form_run_id}/smartva_input.csv | tr ',' '\n' | grep -E 'ageIn|finalAge|isAdult|isChild|isNeonate'
   ```
   At least one must appear and have non-empty values in data rows.

3. Add any new non-standard column prefixes to `_SMARTVA_DROP_PREFIXES` in `va_smartva_02_prepdata.py`.

### ICMR training form specifics

The ICMR01NC0201 form uses a training variant with:
- 32 extra `sa*` social-autopsy columns — diluted WHO ratio below 80%; dropped in prepdata
- `ageInDays` blank for ~50% of records — derived from `finalAgeInYears × 365` in prepdata

### Re-running SmartVA without re-downloading

Use the SmartVA-only trigger path, or from the worker container:

```python
from app import create_app
from app.services.va_data_sync.va_data_sync_01_odkcentral import va_smartva_run_pending
app = create_app()
with app.app_context():
    va_smartva_run_pending()
```

### Richness assessment tooling

DigitVA now includes a standalone analysis script for vendor-aligned SmartVA
field coverage and payload richness scoring:

```bash
docker compose exec minerva_app_service \
  uv run python scripts/smartva_richness_assessment.py --project-code ICMR01
```

This script does not write to SmartVA result tables. It reads current active
payloads and active SmartVA projections, then writes analysis artifacts under
`private/smartva_richness/<timestamp>/`:

- `smartva_field_value_inventory_by_age_group.json`
- `smartva_scope_summary_by_age_group.json`
- `smartva_richness_per_submission.csv`
- `smartva_richness_comparison.csv`
- `smartva_field_differentiators.csv`
- `smartva_field_endorsement_rankings.csv`
- `smartva_who_to_tariff_parameters.csv`
- `smartva_who_to_tariff_parameters.md`
- `smartva_richness_summary.json`

Scoring is per submission, but field scope and technical inventory are age-group
specific (`adult`, `child`, `neonate`). The comparison artifact includes
determined versus undetermined richness summaries overall and by age group. The
field differentiator artifact reports field-level positive-rate deltas for
determined versus undetermined submissions within each age group. Field-facing
outputs now use `short_label` from field config where available, and the
endorsement ranking artifact shows the most positively endorsed SmartVA-scored
fields by age group. The WHO-to-tariff artifacts add a field-level trace from
original WHO question ids and labels to downstream tariff-applied SmartVA
parameters, plus field endorsement percentages and a short writeup on retained,
collapsed, transformed, HCE-gated, and free-text-gated features.

### SmartVA source reference

The full SmartVA-Analyze v3.0.0 source is at `vendor/smartva-analyze`. Key files for troubleshooting:

| File | What to look at |
|---|---|
| `src/smartva/workerthread.py` | Form type detection logic (the 80% threshold) |
| `src/smartva/who_prep.py` | Age field calculation (`calculate_age()`) |
| `src/smartva/common_prep.py` | `gen_5_4*` validation, adult/child/neonate routing |
| `src/smartva/data/common_data.py` | `AGE_VARS` definition, default column list |
| `src/smartva/data/who_data.py` | Full `Id10xxx` → `gen_5_*` column mapping table |
