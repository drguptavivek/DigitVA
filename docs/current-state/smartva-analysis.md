---
title: SmartVA Analysis
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-23
---

# SmartVA Analysis

SmartVA is an automated cause-of-death classification tool for Verbal Autopsy (VA) data. This document covers how DigitVA integrates SmartVA: input preparation, execution, output parsing, result storage, and operational considerations.

SmartVA is installed as a local Python package from `vendor/smartva-analyze` (declared in `pyproject.toml` as `smartva = { path = "vendor/smartva-analyze" }`). Non-Python assets (CSV data files, HTML templates, etc. from `data/` and `res/` directories) are synced into the installed package at build time via `scripts/sync_smartva_package_data.py`, which runs during Docker image build and in the development override startup.

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
- exact raw SmartVA-generated files are copied to disk under the configured
  `APP_SMARTVA_RUNS` base directory per form run for operational debugging, and
  — with `ATTACHMENT_STORE=s3` — archived to the DigitVA bucket under the
  `smartva_runs/` prefix and removed from the VM (see *Disk Preservation and
  Archival*)
- `report.txt` rejection lines are now parsed, and submissions removed by
  SmartVA quality checks are recorded as `smartva_rejected` failures rather
  than generic missing-row failures

See [SmartVA Generation Policy](../policy/smartva-generation-policy.md) for the
policy baseline.

---

## Overview

SmartVA is run as a Python subprocess using the `smartva` package installed
from the local vendor (`vendor/smartva-analyze`). It consumes a CSV exported
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
| Source | `vendor/smartva-analyze` (local package) |
| Install | uv path dependency (`smartva = { path = "vendor/smartva-analyze" }` in `pyproject.toml`) |
| Asset sync | `scripts/sync_smartva_package_data.py` copies CSV/data/res assets into installed package |
| CLI entry point | `python -m smartva.va_cli` |
| Execution environment | `minerva_celery_worker` container |
| Required deps | `click`, `numpy`, `pandas`, `progressbar2`, `stemming`, `python-dateutil`, `xlsxwriter`, `matplotlib`, `colorama`, `pyparsing` (all via transitive deps) |

SmartVA is installed as a local uv path dependency. Non-Python assets (CSV data
files from `data/`, HTML/templates from `res/`) are **not** included in the pip
install, so `scripts/sync_smartva_package_data.py` copies them from the vendor
source into the installed package directory. This runs during Docker image build
and in the development `docker-compose.override.yml` startup.

GUI-only dependencies (`wxpython`, `tornado`) are excluded via
`[tool.uv] exclude-dependencies` in `pyproject.toml`.

### Containers

SmartVA runs inside the Celery worker as a pure Python package. Since SmartVA
is now a native package (no PyInstaller binary), it is architecture-independent
and shares the same Python interpreter as the worker process.

- **`minerva_celery_worker`** — runs SmartVA via Celery tasks (batch size 50, 2-second inter-batch sleep)
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
va_smartva_runsmartva()       # rust engine in-process (libsmartva_rust.so), or the CLI: smartva_input.csv -> smartva_output/
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

SmartVA runs on the engine `SMARTVA_ENGINE` selects
([Runtime and operations](runtime-and-operations.md#smartva-engine)). The
default, `rust`, runs in the worker process: `va_smartva_runsmartva` loads
`libsmartva_rust.so` (`SMARTVA_RS_LIB`, from the same release tarball as the
binary) once per process with `ctypes` and calls `smartva_run_directory`, the
same Rust function the CLI's directory mode runs. It writes the same output
tree, and the trained tariff models stay cached in the process between runs
(see [Throughput](#throughput)). The flag strings are converted with the CLI's
own boolean rule (`true/t/yes/y/1`, `false/f/no/n/0`, case-insensitive; anything
else fails the run). A non-zero return is reported like a failed CLI run.
`SMARTVA_RS_LIB=""` runs the binary as a subprocess instead, with these flags:

```bash
/usr/local/bin/smartva-rs --no-charts --country Unknown \
    --hiv False --malaria False --hce True --freetext True \
    smartva_input.csv smartva_output/
```

`python` (the rollback) runs Python SmartVA with the same flags:

```bash
python -m smartva.va_cli --country=Unknown \
    --figures=False --hiv=False --malaria=False --hce=True --freetext=True \
    smartva_input.csv smartva_output/
```

All three write the same CSV tree, which the rest of this page reads. With
`rust` and the library (or, with `SMARTVA_RS_LIB=""`, the binary) missing, the
run fails (no fallback). Each run's
`run_metadata` also records `"smartva_engine": {"name", "version"}`.

`--hiv` and `--malaria` are resolved per submission, not per form
(`_derive_smartva_run_options` in `va_smartva_02_prepdata.py`, called by
`_generate_batch` in `app/services/smartva_service.py`). For each option
independently: the area preset of the submission's organization unit (nearest
ancestor with a value, `org_grant_service.resolve_unit_va_presets`; `high` is
on, `low`/`veryl` off), else the `va_forms.form_smartvahiv` /
`form_smartvamalaria` flag (no organization tree, unplaced submissions), else
off. The submission's own `Id10002`/`Id10003` answers are not read. The
resolution costs two queries per batch (the submissions' org units, then one
ltree query for every unit's presets). A batch whose submissions resolve to
different option sets is split into one invocation, and one `va_smartva_form_runs`
row, per option set. Each `va_smartva_runs.run_metadata` records
`{"smartva_options": {"hiv": {"value": "True"|"False", "source": ...},
"malaria": {...}}}`, where `source` is the id of the unit whose preset applied,
`"form flag"` or `"default"`. No schema change: `run_metadata` already existed.
Policy: [SmartVA Generation Policy](../policy/smartva-generation-policy.md).

The Python command above is what `SMARTVA_CHARTS` (debugging only) runs, with
`--figures True`. Otherwise the runner starts
[`smartva_cli_no_charts.py`](../../app/utils/va_smartva/smartva_cli_no_charts.py)
in place of `-m smartva.va_cli`: SmartVA imports matplotlib in three modules and
draws two charts even with `--figures False`, nothing in DigitVA reads them, so
the launcher gives SmartVA an empty stand-in for matplotlib, turns those two
charts off and runs SmartVA unchanged. matplotlib's font cache is baked into
the image (`MPLCONFIGDIR=/opt/matplotlib`, built in the `Dockerfile`), never
rebuilt per run. Timing: about 2.6 s for a one-case run on the dev stack (it was
30-40 s while the font cache was rebuilt on every run). Runs are triggered on
interview completion and by a 30 s beat sweep of `smartva_pending`
([Runtime and operations](runtime-and-operations.md)).

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
are processed in groups of `SMARTVA_BATCH_SIZE = 50` submissions per
invocation.

### Throughput

Each completed interview queues `run_smartva_for_submission` for that one
case, so the engine runs once per case. With the CLI, every run rebuilt the
tariff models: on the dev stack a one-row `smartva-rs` run takes ~87 ms, of
which process start is under 1 ms, and each extra row adds ~1 ms (10 rows
94 ms, 27 rows 113 ms). That fixed model build was the cost of a SmartVA task.
The staging load test (2026-10-22, t4g.medium) drained about 2 tasks/s, which
left ~3,350 tasks queued after 5,043 web interviews in 10 minutes.

In-process, the first run in a worker child builds the models (~100 ms) and
later runs reuse them: `smartva_run_directory` takes ~26 ms per one-case run
(it still writes the full output tree, including the xlsx workbooks the app
does not read). Measured on the dev stack (4 vCPU, arm64), engine 3.0.1 both
ways, bead digitva-5gsq:

| Measure | CLI subprocess | In-process | 
|---|---|---|
| One SmartVA task, Flask harness, 965 UNSW01 cases | 109.5 ms (engine 80 ms) | 53.3 ms (engine 26 ms) |
| Tasks/s, same harness | 9.1 | 18.7 |
| Tasks/s, real Celery worker, 300 queued cases | 8.2 | 17.7 |
| Worker child RSS: idle / peak while draining | 165 / 182 MiB | 165 / 236 MiB |
| 200-case sweep (4 batches of 50), wall / child peak | 3.2 s / 185 MiB | 2.8 s / 240 MiB |

Parity: the stored results of all 965 UNSW01 cases (914 adult, 27 child,
24 neonate) are identical field by field, raw likelihood rows included; on 304
inputs every output CSV and `report.txt` matches the CLI's except the line
naming the output folder. The library's RSS settles at ~66 MB in a bare
interpreter and stays there over 400 runs (no growth). The extra ~55 MiB per
worker child is why `--max-memory-per-child` is 300000 KB (docker-compose.yml).

On its own the in-process engine gains about 2x: the task's own database and
file work is then half of its time, and the engine still writes a full output
tree per case. The sweep gains little because it already batches 50 cases per
run.

#### Queued cases run together

An extra case in a run costs ~1 ms, so a starting plain task (neither
`regenerate` nor `requested_by`; bead digitva-96ik) also takes the other queued
plain runs of its form into its batch, up to `SMARTVA_BATCH_SIZE` (50) cases.
`enqueue_smartva` marks a plain run with a second Redis key,
`smartva-plain:<va_sid>` (value: the trigger). The lead's
`claim_queued_plain_runs` takes `smartva_pending` cases of the same form that
have no active current-payload result, are not confirmed duplicates, have the
marker `queued` and carry the same trigger. That keeps each case's stored
`trigger_source` its own. It sets their markers to `running`, drops their
flags, runs everything through `_generate_batch`, and clears their markers
afterwards. Their own tasks then skip: while the batch runs on the
`running` marker, afterwards on `has_current_payload_result`. A claimed case
the batch wrote nothing for has neither, so its own task (or the sweep) runs
it. A claimed case's `running` marker lasts 660 s
(`SMARTVA_CLAIMED_MARKER_TTL_SECONDS`), just past the task's 600 s hard limit.
If the lead is killed, its claimed cases' own tasks have already skipped, and
the sweep runs those cases once their markers expire. Regenerate and Run-button
requests are never taken along and never take others. The claim is not
atomic; with one worker process (concurrency 1) that does not matter.

Measured on the dev stack with the in-process engine 3.0.1 and a real Celery
worker (concurrency 1, 300000 KB memory cap). The cases were queued as
completion runs, with marker and flag set as `enqueue_smartva` sets them, all
before the worker started: a backlog, as on staging. Wall time runs from the
first task's start to the last task's end in the worker log, and includes the
first child's cold model build.

| Backlog | Main: one run per task, child recycled every 100 tasks | Queued cases together, child recycled on memory only |
|---|---|---|
| 965 UNSW01 cases: tasks/s | 20.2 | 195.5 |
| 6,932 ICMR01 cases (7 forms): tasks/s | 11.6 | 135.7 |
| ICMR01: engine runs | 6,932 | 143 (136 of 50) |
| ICMR01: worker busy / idle between tasks | 383 s / 216 s | 49 s / 2 s |
| Worker child peak RSS | 239 MiB | 242 MiB |

The two halves of the change only work together:

- With the 100-task recycle, batching alone gave 21-24 tasks/s on UNSW01. A
  skipped duplicate task takes ~1.5 ms, but it still counts toward the 100,
  and each recycle left the worker idle for ~4 s before the new child started
  (~1-3 s on main). That idle time is inside Celery's prefork pool, after the
  old child has exited. Each recycle also dropped the cached models.
- With no recycle, one run per task reached only 26.5 tasks/s on UNSW01. The
  ~40 ms per task is the task's own work.

So `config.py` now recycles a worker child mainly on memory:
`worker_max_memory_per_child` is 300000 KB, the same as the worker's
command-line flag, and `worker_max_tasks_per_child` is 1000 (owner 2026-10-23)
as a safety net, which costs one ~4 s pause per 1000 tasks. The table above
was measured with no count recycle. A worker started
without that flag, such as the demo stack's, is capped too.

Parity: the stored results of all 965 UNSW01 cases (914 adult, 27 child,
24 neonate) are identical field by field, raw likelihood rows included; on 304
inputs every output CSV and `report.txt` matches the CLI's except the line
naming the output folder. The library's RSS settles at ~66 MB in a bare
interpreter and stays there over 400 runs (no growth). The extra ~55 MiB per
worker child is why `--max-memory-per-child` is 300000 KB (docker-compose.yml).

On its own the in-process engine gains about 2x: the task's own database and
file work is then half of its time, and the engine still writes a full output
tree per case. The sweep gains little because it already batches 50 cases per
run.

#### Queued cases run together

An extra case in a run costs ~1 ms, so a starting plain task (neither
`regenerate` nor `requested_by`; bead digitva-96ik) also takes the other queued
plain runs of its form into its batch, up to `SMARTVA_BATCH_SIZE` (50) cases.
`enqueue_smartva` marks a plain run with a second Redis key,
`smartva-plain:<va_sid>` (value: the trigger). The lead's
`claim_queued_plain_runs` takes `smartva_pending` cases of the same form that
have no active current-payload result, are not confirmed duplicates, have the
marker `queued` and carry the same trigger. That keeps each case's stored
`trigger_source` its own. It sets their markers to `running`, drops their
flags, runs everything through `_generate_batch`, and clears their markers
afterwards. Their own tasks then skip: while the batch runs on the
`running` marker, afterwards on `has_current_payload_result`. A claimed case
the batch wrote nothing for has neither, so its own task (or the sweep) runs
it. A claimed case's `running` marker lasts 660 s
(`SMARTVA_CLAIMED_MARKER_TTL_SECONDS`), just past the task's 600 s hard limit.
If the lead is killed, its claimed cases' own tasks have already skipped, and
the sweep runs those cases once their markers expire. Regenerate and Run-button
requests are never taken along and never take others. The claim is not
atomic; with one worker process (concurrency 1) that does not matter.

Measured on the dev stack with the in-process engine 3.0.1, a real Celery
worker (concurrency 1, `--max-memory-per-child=300000`), 965 UNSW01 cases
queued as completion runs (plain, marker and flag set as `enqueue_smartva`
does). The first case ran alone and is not counted:

| Measure | One run per task | Queued cases together |
|---|---|---|
| Tasks/s, cases queued in sid order | 10.1 | 35.8 |
| Tasks/s, cases queued in shuffled order | | 26.3 |
| Engine runs for 964 cases | 964 | 23 (18 of 50) |
| Worker child RSS: idle / peak while draining | 128 / 237 MiB | 128 / 242 MiB |
| ICMR01, all 7 forms, 6,931 cases, sid order: tasks/s | 16.7 | 27.9 |
| ICMR01: engine runs (child peak RSS) | 6,931 (239 MiB) | 195, 135 of 50 (243 MiB) |

(This harness queues plain runs, which check for an existing result first, so
its one-run-per-task figure is lower than the 17.7 above, which was measured
with regenerate tasks.) Most of the remaining time is the skipped tasks
themselves: Celery delivery, an app context, one Redis read and one indexed
query each.

Parity: the stored results of all 965 UNSW01 cases are identical field by
field to one-case runs, raw likelihood rows, trigger and run metadata included.
That holds over several drains, with the cases queued in sid order and in
shuffled order, which gave different batch compositions (runs of 3 to 50
cases). The same holds for all 6,932 ICMR01 cases over seven forms, in runs of
1 to 50 cases. A run can hold a single case: when the worker catches up with
the queue, a lead finds nothing else queued yet. A case's
result does not depend on the other cases in its run. One difference remains,
and the sweep and `generate_for_form` already have it: a failure of a whole
run (option resolution, input preparation, the engine call) records a failure
for every case in the batch, not only for the case that caused it.

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
- the full raw SmartVA workspace is copied once per form run to the persisted
  `disk_path` recorded in `va_smartva_form_runs` for operational debugging, and
  then archived off the VM — `archive_state` on the same row records where it
  is now
- the current service does **not** write SmartVA workspaces under
  `APP_DATA/SMARTVA_OUTPUT` or `APP_DATA/<form_id>/smartva_input|smartva_output`;
  those older directories are legacy leftovers from a pre-form-run append
  workflow and are not part of the active runtime path

---

## Result Storage

SmartVA result storage is managed by `smartva_service.py`. The save logic per row:

| Condition | Action |
|---|---|
| Submission was amended this sync run (Phase 1 added/updated it) | Deactivate old result, write new one |
| Submission has no existing active result (gap fill) | Write new result regardless of Phase 1 |
| Submission has an existing active result and was not amended | Skip — result is current |
| Submission already has a successful result for current payload version | Skip — already generated |
| SmartVA attempt fails for the current payload | Write an active failure row with `va_smartva_outcome = 'failed'` and failure metadata |

This means every sync run — including SmartVA-only runs — fills in missing results without overwriting results for unchanged submissions. A failed result does NOT block a later successful re-run.

### Four-Table Architecture

| Table | Purpose |
|---|---|
| `va_smartva_form_runs` | Form-level execution metadata (trigger source, pending count, outcome, disk path) |
| `va_smartva_runs` | Per-submission attempt history (outcome, failure stage/detail, payload version, `run_metadata` with the hiv/malaria options and their source) |
| `va_smartva_run_outputs` | Raw likelihood rows from SmartVA CSV output (full JSONB payload per row) |
| `va_smartva_results` | Active projection layer consumed by the coding UI |

### Result Projection (`va_smartva_results`)

Successful rows store the normalized summary: cause1-3 (with ICD codes),
likelihood1-3, key_symptom1-3, all_symptoms, age (formatted `.1f`), sex,
result_for (age group), and payload_version_id.

Failure rows have all cause/likelihood fields NULL, with `va_smartva_outcome =
'failed'` and:

- `va_smartva_failure_stage`: one of `"execution"` (subprocess exception),
  `"format_output"` (no output file), `"missing_row"` (SmartVA completed but no
  row for this SID), or `"smartva_rejected"` (quality check in report.txt)
- `va_smartva_failure_detail`: error message or rejection reason (up to 4000 chars)

Both success and failure rows follow the same active/inactive lifecycle.

### Likelihood Storage (`va_smartva_run_outputs`)

After SmartVA completes, `smartva_service.py` reads the raw likelihood CSVs
from the SmartVA output directory:

- `smartva_output/4-monitoring-and-quality/intermediate-files/adult-likelihoods.csv`
- `smartva_output/4-monitoring-and-quality/intermediate-files/child-likelihoods.csv`
- `smartva_output/4-monitoring-and-quality/intermediate-files/neonate-likelihoods.csv`

Each matching SID's entire row is stored as a JSONB dict in
`va_smartva_run_outputs.output_payload`. The schema is variable — it contains
whatever columns SmartVA emits (cause/likelihood columns, tariff scores, etc.).
Rows are keyed by `output_kind = 'likelihood_row'`,
`output_source_name` (e.g. `"adult-likelihoods.csv"`), and `output_resultfor`
(e.g. `"for_adult"`).

### Disk Preservation and Archival

The entire SmartVA workspace is copied to disk under `APP_SMARTVA_RUNS`:

```
{APP_SMARTVA_RUNS}/{project_id}/{form_id}/{form_run_id}/
  smartva_input.csv
  smartva_output.csv
  smartva_output/
    1-individual-cause-of-death/
      adult-predictions.csv
      child-predictions.csv
      neonate-predictions.csv
    2-csmf/
      csmf.csv
    4-monitoring-and-quality/
      report.txt
      intermediate-files/
        adult-likelihoods.csv
        child-likelihoods.csv
        neonate-likelihoods.csv
```

The `disk_path` in `va_smartva_form_runs` stores the relative path.
Normal regeneration derives from versioned payloads and persisted DB outputs
rather than requiring preserved raw workspaces.

Because nothing in the app reads a run directory once its likelihood rows are
in `va_smartva_run_outputs`, the directory does not stay on the VM. With
`ATTACHMENT_STORE=s3`, `_archive_completed_form_run()` runs immediately after
the batch commits and hands the directory to
`app/services/smartva_run_archive_service.py`, which:

1. uploads every file to
   `smartva_runs/{project_id}/{form_id}/{form_run_id}/{relative path}` in the
   same private bucket the attachments use, with a content type per extension
   (`text/csv`, `text/plain`, `image/png`, the xlsx/docx types), SSE-S3 and
   `Cache-Control: private, no-store`;
2. verifies the whole prefix with one listing — every file present at its full
   size;
3. removes the local directory and NULLs `disk_path`, but only once
   `SMARTVA_RUNS_KEEP_LOCAL_DAYS` (default `0`) has elapsed since the run
   completed.

These objects are **never presigned and never served** — they carry full VA
payloads. Archival never fails a SmartVA run: any error is recorded as
`archive_state = 'failed'` with a short `archive_error_code`, the directory
stays, and the backlog is retried by `flask smartva archive-runs` or the admin
panel's *Archive pending runs* action. On the local attachment store nothing is
archived and nothing is deleted.

Run-archive columns on `va_smartva_form_runs`: `archive_state`
(`local`/`archived`/`failed`/`absent`, indexed), `archive_key_prefix`,
`archived_at`, `archive_error_code`, `archive_file_count`, `archive_bytes`.
Policy baseline: [SmartVA Generation Policy](../policy/smartva-generation-policy.md),
*Run Directory Archival*.

### Audit and Isolation

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
