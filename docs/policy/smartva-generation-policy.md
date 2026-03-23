---
title: SmartVA Generation Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-23
---

# SmartVA Generation Policy

## Purpose

This policy defines when SmartVA cause-of-death analysis should run, how it interacts with the workflow state machine, and what protections exist for finalized submissions.

## Core Principle

SmartVA is an **advisory tool** that provides automated COD suggestions to coders. It must respect the workflow state machine and **not regenerate results for finalized submissions** unless explicitly authorized.

Desired gating rule:

- a submission must not enter `ready_for_coding` until SmartVA has either:
  - been generated for the current payload, or
  - been regenerated for the current payload, or
  - failed for the current payload and that failure has been explicitly
    recorded
- in the target workflow model, SmartVA is therefore a pre-coding gate, not a
  purely downstream side effect of sync
- this gate applies to new payloads and changed payloads
- same-payload workflow returns do not require a fresh SmartVA rerun

Current implementation note:

- current sync now places consent-valid new/changed submissions into
  `smartva_pending`
- successful SmartVA generation transitions `smartva_pending` submissions to
  `ready_for_coding`
- handled SmartVA failure now also transitions `smartva_pending` submissions to
  `ready_for_coding`, but only after a durable failure record is stored for the
  current payload
- SmartVA rows are now linked to `payload_version_id`, and readiness is checked
  against the current active payload version rather than any active result for
  the `va_sid`
- current runtime now stores SmartVA in three layers:
  - `va_smartva_runs` for durable attempt history
  - `va_smartva_run_outputs` for emitted per-run output rows
  - `va_smartva_results` for the active projection row used by the UI

## Workflow State Guards

### Protected States

SmartVA generation is **blocked** for these states (unless forced):

- `coder_finalized` — Final COD is authoritative, SmartVA should not change
- `reviewer_eligible` — Post-24-hour resting state, no automatic SmartVA rerun
- `reviewer_finalized` — Reviewer final COD is authoritative
- `finalized_upstream_changed` — Pending review, no new SmartVA until resolved
- `closed` — Legacy compatibility state only; if such rows exist they remain protected

Current implementation note:

- runtime now writes `reviewer_eligible` rather than `closed` after coder
  recode-window expiry
- `closed` is still defined as a compatibility constant and SmartVA treats it
  as protected if such legacy rows exist

### Automatic Pre-Coding Gate

Automatic SmartVA gating for the current payload belongs on:

- `smartva_pending`

`screening_pending` is an optional project-configured step before
`smartva_pending`. Automatic SmartVA should not run until the submission
actually enters `smartva_pending`.

### Allowed Manual/Admin Regeneration States

Manual or explicitly triggered regeneration may run for eligible non-protected
states such as:

- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

Target workflow meaning:

- `smartva_pending` = synced and workflow-eligible, but not yet cleared for
  coding because SmartVA has not yet been generated, regenerated, or explicitly
  failed-and-recorded for the current payload
- `ready_for_coding` = coding queue eligible only after the current payload has
  undergone a SmartVA attempt and the outcome is recorded

## Generation Operations

### Single Submission (`generate_single`)

```
generate_single(va_sid, force=False)
```

| Workflow State | Has Active Result | force=False | force=True |
|---|---|---|---|
| Allowed | No | Run SmartVA | Run SmartVA |
| Allowed | Yes | Skip (result exists) | Regenerate |
| Protected | * | **SKIP** — return reason | Run SmartVA |

**Authorization for `force=True`:** Admin only

### Form-Level Pending (`generate_pending`)

```
generate_pending(form_id)
```

Finds submissions for the form that:
1. Have NO active SmartVA result for the current active payload version
2. Are in an **allowed** workflow state

Protected submissions are excluded from the pending set.

### Bulk Pending (`generate_all_pending`)

Same behavior as form-level, applied across all active forms.

## Trigger Sources

SmartVA can be triggered from:

| Source | Behavior |
|---|---|
| Full sync (Phase 2) | Runs for `pending_sids ∪ amended_sids`, excludes protected |
| Single form sync | Runs for `pending_sids ∪ amended_sids`, excludes protected |
| Single submission refresh | Runs only if state is allowed, otherwise skip |
| "Gen SmartVA" button | Runs `generate_pending()` for all forms |
| Manual API call | Respects `force` parameter |

## Result Lifecycle

## Storage Baseline

SmartVA storage must be payload-version aware.

Required target behavior:

- every SmartVA attempt must be tied to a specific `payload_version_id`
- every SmartVA attempt must be durably stored, including failures
- SmartVA history must preserve multiple runs for the same `va_sid` across
  payload changes and manual reruns
- SmartVA output storage must not be limited to the flattened top-3 summary row

Required target storage layers:

1. SmartVA run history
   - one row per execution attempt for a `payload_version_id`
   - success/failure outcome
   - execution metadata and timestamps
2. SmartVA per-run outputs
   - normalized storage for emitted likelihood outputs
   - enough detail to reconstruct or analyse the SmartVA result later
3. Active projection
   - one current active result per active payload version used by the app UI
   - this is a projection concern, not the whole SmartVA history

Current implementation note:

- DigitVA now persists durable SmartVA run history in `va_smartva_runs`
- DigitVA now persists emitted raw likelihood rows in `va_smartva_run_outputs`
- DigitVA also persists the formatted result row per run in
  `va_smartva_run_outputs`
- `va_smartva_results` remains the active/inactive projection used by the app

### Active vs Inactive Results

- **Active**: `va_smartva_status = 'active'` — current result shown to coders
- **Inactive**: `va_smartva_status = 'deactive'` — superseded by newer result
- each SmartVA row should be tied to the payload version it applies to via
  `payload_version_id`

Target refinement:

- active/inactive status should describe the current projection row only
- SmartVA run history must remain durable even when a run is no longer the
  active projection

### Success vs Failure Outcome

- **Success**: `va_smartva_outcome = 'success'`
- **Failure**: `va_smartva_outcome = 'failed'`
- failure rows also store:
  - `va_smartva_failure_stage`
  - `va_smartva_failure_detail`

Failure rows are durable SmartVA attempt records for the current payload. They
use the same active/inactive lifecycle as successful SmartVA rows so that a
later payload change or successful rerun can supersede them cleanly.

Target refinement:

- failures must also be preserved in SmartVA run history, not only in the
  current projection layer

### When Results Are Regenerated

| Condition | Action |
|---|---|
| New submission (no result) | Create new active result |
| ODK data changed + allowed state | Deactivate old current-payload result if any, create new active result for the new payload version |
| ODK data changed + protected state | **DO NOT regenerate** |
| Manual force regenerate | Deactivate old, create new active |

Target refinement:

- regeneration creates a new SmartVA run for the same or new
  `payload_version_id`
- regeneration must not erase prior SmartVA run history

### Audit Trail

Every SmartVA result change creates `VaSubmissionsAuditlog` entries:

- `va_smartva_creation_during_datasync` — new result created
- `va_smartva_deletion_during_datasync` — old result deactivated
- `va_smartva_failure_recorded` — failure recorded for the current payload

## Service Architecture

```
SmartVAService
├── generate_single(va_sid, force=False) -> SmartVAResult
├── generate_pending(form_id) -> FormSmartVAResult
├── generate_all_pending() -> BulkSmartVAResult
├── get_active_result(va_sid) -> VaSmartvaResults | None
└── has_active_result(va_sid) -> bool

SmartVAResult:
├── status: "generated" | "skipped_protected" | "skipped_exists" | "error"
├── reason: str (when skipped)
├── result: VaSmartvaResults (when generated)
└── audit_entries: list[VaSubmissionsAuditlog]
```

## Integration with ODK Sync

SmartVA runs **after** ODK sync (Phase 2), but only for submissions that:

1. Were added or updated in Phase 1, AND
2. Are in an allowed workflow state

Desired target sequencing:

1. ODK sync stores or updates the submission
2. consent-valid coding candidates enter `smartva_pending`
3. SmartVA runs
4. on SmartVA generate/regenerate, or on durable failure recording, the
   submission may transition to `ready_for_coding`

```
Phase 1: ODK Sync
├── fetch_submissions()
├── upsert_submissions()
│   ├── Non-protected: normal upsert
│   └── Protected + changed: mark finalized_upstream_changed
└── sync_attachments()

Phase 2: SmartVA
├── get_pending_sids() — excludes protected
├── prep_input_csv()
├── run_smartva_binary()
└── save_results() / record explicit failure

Phase 3: Coding readiness
└── transition eligible submissions to ready_for_coding
```

## Protected Submission Handling

When a submission is in `coder_finalized` or `finalized_upstream_changed`:

1. **Do NOT regenerate SmartVA** during sync
2. **Do NOT modify existing SmartVA result**
3. **Log skip reason** in sync progress
4. **Return skip status** to caller

If an admin forces regeneration:
1. Deactivate existing result (audit logged)
2. Run SmartVA
3. Create new active result (audit logged)
4. Do NOT change workflow state

## Authorization Matrix

| Operation | Coder | Data Manager | Admin |
|---|---|---|---|
| View SmartVA results | Yes (assigned) | Yes (scoped) | Yes |
| Generate pending (form) | No | Yes | Yes |
| Generate pending (all) | No | No | Yes |
| Force regenerate (protected) | No | No | Yes |

## Performance Considerations

- SmartVA is CPU-intensive and runs in the Celery worker container
- Form-level runs process submissions in batches
- Large forms may take several minutes
- Progress is logged to `va_sync_runs.progress_log`

## Related Documents

- [Coding Workflow State Machine Policy](coding-workflow-state-machine.md)
- [ODK Sync Policy](odk-sync-policy.md)
- [SmartVA Analysis Current State](../current-state/smartva-analysis.md)
