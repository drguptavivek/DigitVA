# Handoff

## Current State

- Workflow refactor, payload-version linkage, reviewer flow, and SmartVA run-history work are in place.
- SmartVA redesign is now partly implemented:
- SmartVA redesign is now substantially implemented:
  - `VaSmartvaFormRun` exists
  - `VaSmartvaRun.form_run_id` exists
  - SmartVA prep now reads from `VaSubmissionPayloadVersion.payload_data`
  - raw SmartVA workspaces are copied to disk under `APP_DATA/smartva_runs/...`
  - `VaSmartvaRunArtifact` has been removed from the active runtime path
  - `report.txt` rejections now record `smartva_rejected` failures with the
    SmartVA-provided reason text
- All 19 SmartVA service tests passing.

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

## Remaining SmartVA Plan

1. Update any remaining readers/reporting paths that still assume old SmartVA storage details.
2. Decide whether to broaden the backfill beyond `UNSW01`.
3. If broader rollout is wanted, repeat the scoped backfill by project/site using the same script.

## Uncommitted Files (need commit)

- `app/services/smartva_service.py` — workspace fix + earlier refactor
- `tests/services/test_smartva_service.py`
- `scripts/backfill_smartva_current_outputs.py`
- `handoff.md`
- Various docs/task files

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
