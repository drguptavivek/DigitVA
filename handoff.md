# Handoff

## Current State

- Workflow refactor, payload-version linkage, reviewer flow, and SmartVA run-history work are in place.
- SmartVA backfill is complete for all projects (UNSW01, ICMR01, ZZZ99).
- State machine / ODK sync / reviewer signal audit completed. All sync and coding/recoding track fixes committed.
- SmartVA reader/reporting parity audit: clean — no work needed (verified 2026-03-24).
- Remaining open tracks: schema gap for reviewer COD snapshot (deferred migration).

## What Was Done This Session (cont.)

### 4. Reviewer session timeout — Track 4 DONE

Full reviewer allocation timeout path implemented and tested.

**Problem:** `reviewer_coding_in_progress` allocations had no automatic release
path. A reviewer who abandoned a session mid-way would leave the submission
stuck in `reviewer_coding_in_progress` indefinitely.

**Policy:** reviewer final COD is the only terminal action. All intermediate
saves (NQA, Social Autopsy, reviewer NQA via `VaReviewerReview`) are partial.
On timeout, all intermediate artifacts are deactivated and the submission
returns to `reviewer_eligible`.

Files changed:

- `app/services/workflow/definition.py` — `TRANSITION_INCOMPLETE_REVIEWER_RESET`
  and its `TransitionDefinition` (target: `reviewer_eligible`)
- `app/services/workflow/transitions.py` — `reset_incomplete_reviewer_session()`
  function; `ADMIN_ACTOR_KINDS` rename from `DEMO_ACTOR_KINDS`; admin override
  expanded to `reviewer_eligible` source
- `app/services/coding_allocation_service.py` — `_deactivate_reviewer_session_artifacts()`
  and `release_stale_reviewer_allocations()`
- `app/tasks/sync_tasks.py` — `release_stale_reviewer_allocations_task` extended
  to call `release_stale_reviewer_allocations()` alongside the coder path
- `app/services/reviewer_coding_service.py` — opportunistic call to
  `release_stale_reviewer_allocations()` at the top of `start_reviewer_coding()`
- `docs/policy/coding-allocation-timeouts.md` — reviewer track section added;
  all three timeout paths documented

Tests: 50 passing (coding allocation + sync + workflow suites).

---

## What Was Done This Session (previous context)

### 1. Reviewer dashboard and permissions — Option C (commit `1f72ed8`)

The reviewer dashboard and all reviewer permission utilities now use
`VaSubmissionWorkflow.workflow_state` as the canonical signal. NQA
(`VaReviewerReview`) and Social Autopsy are supporting artifacts and no
longer affect any permission gate or dashboard count.

Files changed:
- `app/routes/reviewing.py` — dashboard list uses workflow state join;
  `va_forms_completed` counts from `VaReviewerFinalAssessments` by current user
- `app/utils/va_permission/va_permission_07_ensurenotreviewed.py` — workflow state primary; NQA presence no longer blocks
- `app/utils/va_permission/va_permission_08_ensurereviewed.py` — checks only `VaReviewerFinalAssessments` by current user
- `app/utils/va_permission/va_permission_10_reviewedonce.py` — checks `workflow_state == reviewer_finalized` only

### 3. Coding/recoding track fixes (commit `TBD — current`)

**`not_selected_for_reviewer` removed from policy.** The state was listed as
"recommended" but never implemented and has no allocation/sampling mechanism.
`coding-workflow-state-machine.md` now explicitly states that unselected cases
remain in `reviewer_eligible` indefinitely and this state should not be added
until a reviewer-sampling feature is designed.

**`DEMO_ACTOR_KINDS` renamed to `ADMIN_ACTOR_KINDS`** in `transitions.py`. The
old constant was a frozenset of a single admin actor being reused across two
unrelated transitions (demo coding and admin override). Both now use the
correctly named `ADMIN_ACTOR_KINDS`. The alias has been removed.

**Admin override now allows from `reviewer_eligible`** in
`mark_admin_override_to_recode()`. Previously only `coder_finalized` was
permitted; the policy said `reviewer_eligible` should also be allowed (cases
there have no active session). `coding-workflow-state-machine.md` updated to
document both permitted source states and explicitly exclude
`reviewer_coding_in_progress` and `reviewer_finalized`.

Files changed:
- `app/services/workflow/transitions.py` — `ADMIN_ACTOR_KINDS`, expanded `allowed_from`, `DEMO_ACTOR_KINDS` removed
- `docs/policy/coding-workflow-state-machine.md` — reviewer states section, admin reset section

### 2. Sync track hardening — state machine policy audit (commit `62cd5ee`)

Cross-checked `coding-workflow-state-machine.md`, `odk-sync-policy.md`,
`definition.py`, `transitions.py`, `va_data_sync_01_odkcentral.py`, and
`data_management_service.py` for consistency and gaps.

Code fixes:
- `reviewer_coding_in_progress` added to `PROTECTED_WORKFLOW_STATES` in
  `definition.py`. An active reviewer session is now protected from ODK
  re-routing (same as `reviewer_eligible`/`reviewer_finalized`).
  `SMARTVA_BLOCKED_WORKFLOW_STATES` inherits this automatically.
- `SYNC_PROTECTED_STATES` local duplicate removed from sync service; now
  imports `PROTECTED_WORKFLOW_STATES` from `definition.py` so they cannot drift.
- Non-protected update path in `va_data_sync_01_odkcentral.py` now:
  - Deactivates `VaDataManagerReview` (stale exclusion artifact cleared when ODK
    data changes on a `not_codeable_by_data_manager` case)
  - Releases `VaAllocations` immediately (coder session invalidated on payload
    change rather than waiting for timeout)

Policy fixes:
- `coding-workflow-state-machine.md`: `consent_refused` added to canonical
  state list; `reviewer_coding_in_progress` added to protected states;
  `not_codeable_*` re-sync behavior documented; status changed to `active`
- `odk-sync-policy.md`: same additions; non-protected behavior clarified;
  Desired State Snapshot label corrected to "data manager or admin"

### Items confirmed correct (no change needed)

- `dm_reject_upstream_change` already uses `workflow_state_before` from the
  pending upstream change record to restore exact pre-change state — was
  incorrectly identified as a bug, code is correct.
- `dm_accept_upstream_change` already deactivates `VaReviewerFinalAssessments`
  and clears authority via `upsert_final_cod_authority(va_sid, None)`.

## SmartVA Architecture — Current Design

### DB Tables (target)

- **`VaSmartvaFormRun`** — one per SmartVA execution (any size: 1 to N submissions)
  - `form_run_id`, `form_id`, `project_id`, `trigger_source`, `pending_sid_count`, `outcome`, `disk_path`, `run_started_at`, `run_completed_at`
- **`VaSmartvaRun`** — has `form_run_id` FK → `VaSmartvaFormRun`
- **`VaSmartvaRunOutput`** — likelihood rows only; `smartva_input_row` and `formatted_result_row` kinds retired
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

`va_smartva_prepdata` reads from `VaSubmissionPayloadVersion.payload_data`
directly. Flat CSV write in sync is dead code.

### SmartVA Neonate Age Gap — Fixed And Verified

**Previous problem:** 24 UNSW01 submissions rejected by SmartVA with
`does not have valid age data`.

**Root cause:** WHO 2022 date-derived path populates `ageInDays` but leaves
`age_group`, `age_neonate_days`, `age_neonate_hours` null.

**Implemented fix:** `app/utils/va_smartva/va_smartva_02_prepdata.py` now
synthesizes `age_neonate_days = int(ageInDays)` when `ageInDays <= 28` and
the manual-path fields are blank.

**Policy ref:** `docs/policy/who-2022-age-derivation.md`

**Verification:** UNSW01, 4 forms, zero rejections after fix.

## SmartVA Backfill — Complete

All projects processed. Global candidate count is zero.

- UNSW01: 965 updated (4 forms)
- ICMR01: 6955 updated (7 forms)
- ZZZ99: 1 processed, `outcome=failed` (expected — test fixture only)
- Backfill script skips `outcome=failed` + non-null `disk_path` (terminal state)

## Remaining Work — Priority Order

The state machine / sync / SmartVA / coding / reviewing audit identified the
following remaining tracks. Work them in this order:

### Track 2 — SmartVA — DONE

Reader/reporting parity audit (2026-03-24): all 13 files checked — routes,
services, utilities, templates. Every SmartVA read uses new semantics
(`VaSmartvaResults`, `VaSmartvaRun`/`VaSmartvaFormRun`, disk-backed files).
No legacy `VaSmartvaRunArtifact` references, no old artifact kinds, no
DB-stored result bytes anywhere in active code. Old artifact table already
dropped. No code changes needed.

### Track 3 — Coding and recoding — DONE

All items resolved:
- Admin override expanded to allow from `reviewer_eligible` ✅
- `DEMO_ACTOR_KINDS` → `ADMIN_ACTOR_KINDS` ✅
- `not_selected_for_reviewer` removed from policy ✅
- Schema gap documented below as a deferred migration item

### Track 6 — Route/UI legacy semantics cleanup — DONE

**NQA save bug fixed**: `vareviewform` handler in `va_form.py` was wrongly deactivating
the reviewer's `reviewing` allocation on NQA save. Allocation release belongs exclusively
in `submit_reviewer_final_cod()` (reviewer's terminal action). Bug removed; comment added.

**Workflow event history surfaced**:
- New JSON API: `GET /api/v1/workflow/events/<va_sid>` (`app/routes/api/workflow.py`)
  — registered under `api_v1` at `/api/v1/workflow/`
- New HTMX partial: `GET /vaform/<va_sid>/workflow_history`
  — renders `app/templates/va_form_partials/workflow_history.html`

Files changed:
- `app/routes/va_form.py` — NQA allocation bug fixed; `workflow_history` partial handler added;
  `VaSubmissionWorkflowEvent` added to imports
- `app/routes/api/workflow.py` — new file; `GET /events/<va_sid>` endpoint
- `app/routes/api/__init__.py` — `workflow.bp` registered at `/workflow`
- `app/templates/va_form_partials/workflow_history.html` — new template

---

### Track 4 — Reviewing — DONE

1. **Reviewer session timeout** ✅ — full path implemented. See "What Was Done
   This Session (cont.)" above.

2. **`VaSubmissionWorkflow` event history** — surfaced via:
   - `GET /api/v1/workflow/events/<va_sid>` — JSON list of all events in chronological order
   - `GET /vaform/<va_sid>/workflow_history` — HTMX HTML partial (for embedding in form views)
   - Template: `app/templates/va_form_partials/workflow_history.html`

### Track 5 — Admin override — DONE

Bug found and fixed: `admin_override_to_recode()` in `coder_workflow_service.py`
still had an old guard rejecting anything other than `coder_finalized`. The
`transitions.py` was already updated to allow both `coder_finalized` and
`reviewer_eligible`, but the service never reached the transition check.

Fix: service guard updated to `not in (WORKFLOW_CODER_FINALIZED, WORKFLOW_REVIEWER_ELIGIBLE)`.

Reviewer artifacts on admin override from `reviewer_eligible`:
- No active reviewer allocation exists (protected state blocks override from
  `reviewer_coding_in_progress`)
- No active reviewer COD exists (reviewer never finalized)
- Any stale intermediate artifacts from a prior timed-out session are already
  cleaned up by the reviewer timeout release
- Recode episode seeded from coder's authoritative final COD — correct for both
  source states

Policy updated in `coding-workflow-state-machine.md` (Admin reset interaction
section) to document reviewer artifact behavior on override.

## Schema Gap — RESOLVED

`va_submission_upstream_changes` now has `previous_reviewer_final_assessment_id`
(nullable FK to `va_reviewer_final_assessments`). When a `reviewer_finalized`
case gets an upstream change, the snapshot captures both the coder COD and the
reviewer COD. Migration: `aacf89977029`.

## Analytics MV — `finalized_upstream_changed` now counted as Coded

Policy: Option C — include `finalized_upstream_changed` cases in coded counts,
flag them clearly. Changes:

- Analytics MV now has `cod_pending_upstream_review` boolean column
  (`true` when `workflow_state = 'finalized_upstream_changed'`)
- KPI `coded_submissions` count now includes `finalized_upstream_changed`
- Dashboard KPI card label changed from "Revoked" → "Data Changed"
- Migration: `b1c2d3e4f5a6` rebuilds the MV with the new column

## Recent Commits

- `62cd5ee` — `Harden ODK sync: protect reviewer mid-session, clear stale exclusions`
- `1f72ed8` — `Use workflow state as canonical reviewer signal (Option C)`
- `a0a9f69` — `Implement NQA/reviewer separation in va_form route handler`
- `ed34f16` — `Refactor SmartVA run storage and backfill current outputs`
- `949a652` — `Tighten recode reset target and untrack beads runtime files`

## Related Task Files

- Primary sync/SmartVA lineage task:
  - [`.tasks/odk-payload-version-sync-cutover.md`](.tasks/odk-payload-version-sync-cutover.md)
- Broader workflow state-machine task:
  - [`.tasks/workflow-bpmn-refactor-plan.md`](.tasks/workflow-bpmn-refactor-plan.md)

## Related Policy And Current-State Docs

- Policy:
  - [`docs/policy/coding-workflow-state-machine.md`](docs/policy/coding-workflow-state-machine.md) — canonical; status active
  - [`docs/policy/odk-sync-policy.md`](docs/policy/odk-sync-policy.md)
  - [`docs/policy/coding-allocation-timeouts.md`](docs/policy/coding-allocation-timeouts.md) — reviewer track not yet covered
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

Run focused test suites after changes:
```bash
# Sync + workflow
docker compose exec minerva_app_service uv run pytest tests/services/test_odk_sync_service.py tests/services/test_odk_sync_workflow_guards.py tests/services/test_submission_workflow_service.py tests/services/test_coding_allocation_service.py -q

# SmartVA
docker compose exec minerva_app_service uv run pytest tests/services/test_smartva_service.py -q

# Data management (upstream change accept/reject)
docker compose exec minerva_app_service uv run pytest tests/services/test_data_management_service.py -q
```
