# Handoff

## Current State

- Workflow refactor, payload-version linkage, reviewer flow, and SmartVA run-history work are in place.
- SmartVA redesign is now substantially implemented:
  - `VaSmartvaFormRun` exists
  - `VaSmartvaRun.form_run_id` exists
  - SmartVA prep now reads from `VaSubmissionPayloadVersion.payload_data`
  - raw SmartVA workspaces are copied to disk under `APP_DATA/smartva_runs/...`
  - `VaSmartvaRunArtifact` has been removed from the active runtime path
  - `report.txt` rejections now record `smartva_rejected` failures with the
    SmartVA-provided reason text
- SmartVA service tests are green (`20 passed` in the focused file).
- Workflow cleanup after the SmartVA refactor is also in:
  - `reset_incomplete_recode()` now always resets to `coder_finalized`
  - `partial_coding_saved` is treated as a legacy compatibility state
  - canonical `SMARTVA_BLOCKED_WORKFLOW_STATES` exists, so
    `consent_refused` is blocked for SmartVA without being mislabeled as a
    finalized protected state

## SmartVA Architecture — Current Design

### DB Tables (target)

- **`VaSmartvaFormRun`** — one per SmartVA execution (any size: 1 to N submissions)
  - `form_run_id`, `form_id`, `project_id`, `trigger_source`, `pending_sid_count`, `outcome`, `disk_path`, `run_started_at`, `run_completed_at`
- **`VaSmartvaRun`** — add `form_run_id` FK → `VaSmartvaFormRun`
- **`VaSmartvaRunOutput`** — keep likelihood rows only; drop `smartva_input_row` and `formatted_result_row` kinds
- **`VaSmartvaRunArtifact`** — retired from the active runtime design
- **`VaSmartvaResults`** — unchanged (active projection)

### On Disk

```
data/smartva_runs/{project_id}/{form_id}/{form_run_id}/
    smartva_input.csv
    smartva_output.csv
    smartva_output/1-individual-cause-of-death/...
    smartva_output/4-monitoring-and-quality/...
```

No per-submission workbooks. No artifact bytes in DB. Files stored once per form run.

### prepdata — DB payload source

`va_smartva_prepdata` must read from `VaSubmissionPayloadVersion.payload_data` directly instead of flat CSV `data/{form_id}/{odk_form_id}.csv`. Flat CSV write in sync becomes dead code and can be removed. Same preprocessing logic (column drop, nan clean, age derivation).

### SmartVA Neonate Age Gap — Fixed And Verified

**Previous problem:** 24 UNSW01 submissions were rejected by SmartVA with
`does not have valid age data`.

Affected forms and counts:
- UNSW01KA0101: 15 rejected (8 zero-day + 7 neonate ≤28d)
- UNSW01NC0101: 9 rejected (5 zero-day + 4 neonate ≤28d)
- UNSW01KL0101: 0 rejected
- UNSW01TR0101: 0 rejected

**Root cause:** These submissions went through the WHO 2022 date-derived age
path so `ageInDays` is populated (0, 3, 13 days etc.) but
`age_group`, `age_neonate_days`, `age_neonate_hours` are all null.
SmartVA needs one of the manual-path fields to classify the case.

**Implemented fix:** In
[`app/utils/va_smartva/va_smartva_02_prepdata.py`](app/utils/va_smartva/va_smartva_02_prepdata.py),
step 3 in the row-processing loop now synthesizes
`age_neonate_days = int(ageInDays)` when:
- `ageInDays <= 28`
- `age_group` is blank
- `age_neonate_days` is blank
- `age_adult` is blank

**Policy ref:** [`docs/policy/who-2022-age-derivation.md`](docs/policy/who-2022-age-derivation.md)
now includes a `SmartVA Preprocessing Requirements` section documenting the
problem, root cause, synthesis rule, and the zero-day edge case.

**Verification outcome:** `UNSW01` project, 4 forms, zero rejections after the
fix. All 24 previously rejected neonate/zero-day submissions now pass through
SmartVA.

**Probe run outputs saved to:** `output/smartva_probe_UNSW01{KA,KL,NC,TR}0101/`

## Completed Backfill Rollout

- Scoped `UNSW01` backfill completed successfully.
- Project/site coverage:
  - `UNSW01KA0101`: 256 saved
  - `UNSW01KL0101`: 255 saved
  - `UNSW01NC0101`: 227 saved
  - `UNSW01TR0101`: 227 saved
- Total updated: `965`
- Failed forms: `0`
- Exported run directories written to:
  - `output/smartva_backfill_runs/UNSW01/...`
- Post-run dry check:
  - `candidate submissions: 0`
  - `candidate forms: 0`

- Scoped `ICMR01` backfill completed successfully.
- Project/site coverage:
  - `ICMR01ML0101`: 1104 saved
  - `ICMR01MP0101`: 1077 saved
  - `ICMR01NC0201`: 139 saved
  - `ICMR01ND0101`: 820 saved
  - `ICMR01OD0101`: 1258 saved
  - `ICMR01PY0101`: 1388 saved
  - `ICMR01RJ0101`: 1169 saved
- Total updated: `6955`
- Failed forms: `0`
- Exported run directories written to:
  - `output/smartva_backfill_runs/ICMR01/...`
- Post-run dry check:
  - `candidate submissions: 0`
  - `candidate forms: 0`

- `ZZZ99` (test fixture) backfill attempted.
  - `ZZZ99ZZ9901`: 1 processed — SmartVA ran, `outcome=failed` (expected: test
    fixture has no real VA questionnaire fields, only `form_def/updatedAt/sid`)
  - Backfill script updated: submissions with `outcome=failed` + existing
    `disk_path` are now excluded from candidates (terminal state; retrying will
    not help).
  - Post-fix global dry check: `candidate submissions: 0`, `candidate forms: 0`

## SmartVA Backfill — Complete

All projects processed. Global candidate count is zero. The backfill is complete.

- **Backfill script fix:** `scripts/backfill_smartva_current_outputs.py` now
  skips submissions whose linked form run has `outcome=failed` with a non-null
  `disk_path`. These submissions were genuinely attempted; retrying produces the
  same result.

## Remaining SmartVA Plan

1. Update any remaining readers/reporting paths that still assume old SmartVA storage details.

## Detailed Next Steps

### 1. Finish remaining project backfills

Run the existing script project-by-project rather than as one global batch:

```bash
docker compose exec minerva_app_service uv run python scripts/backfill_smartva_current_outputs.py --dry-run --project-id <PROJECT_ID>
docker compose exec minerva_app_service uv run python scripts/backfill_smartva_current_outputs.py --project-id <PROJECT_ID>
docker compose exec minerva_app_service uv run python scripts/backfill_smartva_current_outputs.py --dry-run --project-id <PROJECT_ID>
```

Expected pattern:
- first dry run shows non-zero `candidate submissions`
- real run saves all pending rows and exports run directories
- second dry run returns:
  - `candidate submissions: 0`
  - `candidate forms: 0`

Suggested rollout order:
- next remaining project with the largest outstanding candidate set first
- then proceed one project at a time until all are zero

### 2. Validate exported run directories after each project

After each project run:

```bash
find output/smartva_backfill_runs/<PROJECT_ID> -maxdepth 2 -type d | sort
```

Confirm:
- one form directory per processed form
- one `form_run_id` directory under each form
- copied SmartVA workspace exists under each `form_run_id`

### 3. Keep runtime verification narrow and repeatable

If SmartVA service code changes again, rerun:

```bash
docker compose exec minerva_app_service uv run pytest tests/services/test_smartva_service.py -q
docker compose exec minerva_app_service uv run pytest tests/services/test_submission_workflow_service.py tests/services/test_coding_allocation_service.py -q
```

If ODK/sync payload lineage changes again, rerun:

```bash
docker compose exec minerva_app_service uv run pytest tests/services/test_odk_sync_service.py tests/services/test_odk_sync_workflow_guards.py tests/services/test_data_management_service.py -q
```

### 4. Reader/reporting parity checks

Remaining cleanup is mostly downstream readers that may still assume older SmartVA storage details.

Check for:
- direct assumptions that one SmartVA result row is the only durable record
- code that expects DB-stored formatted result artifacts rather than disk-backed form runs
- reporting paths that should use:
  - `VaSmartvaResults` for the active projection
  - `VaSmartvaRun` / `VaSmartvaFormRun` for history and provenance

### 5. Keep workflow assumptions aligned

Relevant workflow points now in force:
- `partial_coding_saved` is legacy compatibility only
- `reset_incomplete_recode()` always returns to `coder_finalized`
- `consent_refused` is blocked for SmartVA via `SMARTVA_BLOCKED_WORKFLOW_STATES`

If any later code introduces a new partial-save transition, it must be added explicitly as a named workflow transition rather than reusing legacy state references implicitly.

### 6. If a future session needs a quick SmartVA probe

Use the existing one-form probe command in the `Useful Commands` section below.
That is the fastest way to inspect exactly what SmartVA generated for a form without changing the active backfill logic.

## Route/State-Machine Integration — Remaining Cleanup

The workflow/state-machine layer is mostly integrated already, but it is not yet a complete “all route behavior goes through one backend contract” finish.

Remaining route-layer cleanup:

1. Keep unifying old server-rendered flows with API/service paths.
   - State-changing behavior should continue to move behind shared services and named transitions.
   - Route handlers should stay thin: auth + request parsing + service call.

2. Retire leftover legacy reviewer semantics from routes/templates.
   - Reviewer is now a secondary coding path, not the old accept/reject review artifact.
   - Any route/UI path still centered on `VaReviewerReview` semantics should be separated from reviewer coding or retired.

3. Keep authorization and workflow validation separated.
   - Routes decide whether the caller may invoke the action.
   - Workflow services/transitions decide whether the state change itself is valid.

4. Improve route/UI exposure of workflow event history.
   - Current state is already canonical in `va_submission_workflow`.
   - Repair/recode/upstream-change cycle history should increasingly come from `va_submission_workflow_events`.

5. Do not let new route flows create legacy compatibility states.
   - `partial_coding_saved` and legacy `closed` should remain readable/compatible only.
   - New runtime flows should not target them.

## Recent Commits

- `ed34f16` — `Refactor SmartVA run storage and backfill current outputs`
- `949a652` — `Tighten recode reset target and untrack beads runtime files`

## Related Task Files

- Primary sync/SmartVA lineage task:
  - [`.tasks/odk-payload-version-sync-cutover.md`](.tasks/odk-payload-version-sync-cutover.md)
- Broader workflow state-machine task:
  - [`.tasks/workflow-bpmn-refactor-plan.md`](.tasks/workflow-bpmn-refactor-plan.md)

## Related Policy And Current-State Docs

- Policy:
  - [`docs/policy/odk-sync-policy.md`](docs/policy/odk-sync-policy.md)
  - [`docs/policy/smartva-generation-policy.md`](docs/policy/smartva-generation-policy.md)
  - [`docs/policy/who-2022-age-derivation.md`](docs/policy/who-2022-age-derivation.md)
  - [`docs/policy/final-cod-authority.md`](docs/policy/final-cod-authority.md)
- Current state:
  - [`docs/current-state/odk-sync.md`](docs/current-state/odk-sync.md)
  - [`docs/current-state/smartva-analysis.md`](docs/current-state/smartva-analysis.md)
  - [`docs/current-state/data-model.md`](docs/current-state/data-model.md)
  - [`docs/current-state/workflow-and-permissions.md`](docs/current-state/workflow-and-permissions.md)

## Useful Commands

Check for lingering backfill process:
```bash
docker compose exec minerva_app_service ps aux
```

Run SmartVA probe for a form and capture all outputs:
```bash
docker compose exec minerva_app_service uv run python -c "
import os, shutil, tempfile
from app import create_app, db
from app.models import VaForms
from app.utils import va_smartva_prepdata, va_smartva_runsmartva
app = create_app()
with app.app_context():
    va_form = db.session.get(VaForms, 'UNSW01NC0101')
    with tempfile.TemporaryDirectory() as workspace_dir:
        va_smartva_prepdata(va_form, workspace_dir, pending_sids=None)
        va_smartva_runsmartva(va_form, workspace_dir)
        shutil.copytree(workspace_dir, '/app/output/smartva_probe_UNSW01NC0101', dirs_exist_ok=True)
"
```
