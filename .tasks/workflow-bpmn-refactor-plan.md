# Workflow BPMN-Style Refactor Plan

- Status: pending
- Priority: high
- Created: 2026-03-20
- Goal: Replace scattered submission workflow state writes with a clean, explicit workflow package that separates submission state, coding intake mode, transition guards, and transition side effects.

## Context

The current workflow logic is spread across sync, SmartVA, coder allocation,
coder form routes, data-management actions, and cleanup jobs.

This creates four problems:

1. workflow state semantics are not owned in one place
2. coding intake mode and submission state are easy to conflate
3. payload-changing transitions and same-payload resets are mixed together
4. protected upstream-change handling is only partially durable

The target architecture is BPMN-like in structure, but implemented as explicit
Python services over the existing database model rather than by introducing an
external BPMN engine or Airflow.

## Design Rules

1. Submission workflow state is one canonical persisted state per submission.
2. Coding intake mode is project configuration, not submission workflow state.
3. All state changes go through named transition functions.
4. Routes, sync code, and background jobs must not write workflow state
   directly.
5. Payload-changing transitions must be distinguishable from workflow-only
   resets that do not require SmartVA rerun.
6. Protected finalized-state upstream changes must preserve history and remain
   auditable.
7. Refactor in staged slices toward a clean final workflow package layout; do
   not leave a long-lived half-migrated workflow layer behind.
8. Every BPMN-style workflow message or event must be logged.

## Event Logging Rule

Every workflow event must produce durable traceability.

Minimum requirement for each event:

- submission id
- event/transition id
- previous state
- current state
- actor role
- actor id when available
- reason / trigger
- timestamp

Logging layers:

- durable DB audit/event record for workflow traceability
- application log message for operational debugging

This applies to:

- sync-routed payload events
- SmartVA completion or failure-recording events
- coder start/save/finalize/not-codeable events
- data-manager triage and upstream-resolution events
- admin override and recode events
- timeout/demo cleanup reset events

State persistence alone is not sufficient. The transition itself must be
traceable as an event.

## Canonical Submission Workflow States

- `screening_pending`
  Optional and project-configured. Some projects may bypass it entirely.
- `smartva_pending`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved`
- `coder_finalized`
- `finalized_upstream_changed`
  Current persisted key; migrated from legacy `revoked_va_data_changed`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`
- `consent_refused`
- `reviewer_eligible`
  Post-24-hour state after coder recode window expiry
- `closed`
  Legacy compatibility only; not part of the active BPMN

## Intake Modes

Project-level intake modes:

- `random_form_allocation`
- `pick_and_choose`

Rules:

- intake mode determines how a coder enters work
- intake mode does not alter downstream submission state semantics
- both modes converge on the same workflow transition:
  `ready_for_coding -> coding_in_progress`

## Target Package Layout

Create and stabilize:

1. `app/services/workflow/__init__.py`
2. `app/services/workflow/definition.py`
   states, transition ids, labels, protected flags
3. `app/services/workflow/intake_modes.py`
   project-level random vs pick-and-choose helpers
4. `app/services/workflow/state_store.py`
   canonical state persistence helpers
5. `app/services/workflow/transitions.py`
   named transition entrypoints
6. `app/services/workflow/upstream_changes.py`
   protected-upstream-change snapshots and resolution helpers

Future likely additions:

7. `app/services/workflow/guards.py`
8. `app/services/workflow/effects.py`
9. `app/services/workflow/notifications.py`

## Architectural Ordering

The workflow package must be used in this order:

1. `definition.py`
   Defines vocabulary only.
2. `intake_modes.py`
   Defines project-level coding entry mode only.
3. `state_store.py`
   Persists canonical workflow state and infers fallback state from legacy rows.
4. `transitions.py`
   Applies business transitions over the canonical definitions and state store.
5. `upstream_changes.py`
   Handles the protected upstream-change subprocess and its durable records.
6. `guards.py` and `effects.py`
   Optional later split once transition logic is stable.

Rules:

- lower layers must not import higher layers
- `state_store.py` must not depend on `transitions.py`
- `intake_modes.py` must not define submission states
- callers outside the workflow package must use `transitions.py` for workflow
  changes

## Transition Inventory

### Sync and SmartVA

- `sync_new_payload_routed`
  - consent valid and screening enabled -> `screening_pending`
  - consent valid and screening bypassed -> `smartva_pending`
  - consent invalid -> `consent_refused`
- `screening_passed`
  - `screening_pending -> smartva_pending`
- `screening_rejected`
  - `screening_pending -> not_codeable_by_data_manager`
- `upstream_change_detected`
  - protected finalized submission with changed payload
  - target state: `finalized_upstream_changed`
- `smartva_completed`
  - `smartva_pending -> ready_for_coding`
- `smartva_failed_recorded`
  - required future transition
  - `smartva_pending -> ready_for_coding`
  - must persist explicit failure record for the current payload

### Coding

- `coding_started`
  - `ready_for_coding -> coding_in_progress`
  - valid for both random and pick intake paths
- `coder_step1_saved`
  - `coding_in_progress|partial_coding_saved -> coder_step1_saved`
- `coder_finalized`
  - `coder_step1_saved|coding_in_progress|partial_coding_saved -> coder_finalized`
- `coder_not_codeable`
  - coding-active states -> `not_codeable_by_coder`
- `data_manager_not_codeable`
  - screening/SmartVA/ready states -> `not_codeable_by_data_manager`

### Reset and Recovery

- `incomplete_first_pass_reset`
  - timeout or abandonment without protected final COD
  - target: `ready_for_coding`
  - no SmartVA rerun
- `incomplete_recode_reset`
  - timeout or abandonment during active recode episode
  - target: `coder_finalized`
  - preserve authoritative final COD
- `demo_started`
  - admin demo path -> `coding_in_progress`
- `demo_reset`
  - restore inferred non-demo workflow state from remaining active records

### Protected Upstream Change Resolution

- `upstream_change_accepted`
  - `finalized_upstream_changed -> smartva_pending`
  - because payload changed, SmartVA must rerun
- `upstream_change_rejected`
  - `finalized_upstream_changed -> coder_finalized`
  - preserve prior authoritative COD

### Future Admin/Recode

- `admin_override_to_recode`
  - same payload
  - target likely `ready_for_coding`
  - no SmartVA rerun
- `recode_started`
- `recode_finalized`
- `reviewer_eligible_after_recode_window`
  - `coder_finalized -> reviewer_eligible`

Current target note:

- `closed` is no longer an active BPMN destination for ordinary cases
- `reviewer_eligible` is the durable post-24-hour resting state
- reviewer selection remains optional and open-ended

## Transition Execution Ordering

Every transition must execute in this order:

1. identify trigger/event
2. load current state
3. validate guard / allowed-from rule
4. emit durable workflow event log entry
5. persist canonical workflow state change
6. run domain side effects
7. emit side-effect success/failure audit/log entries
8. commit transaction

Rules:

- side effects must not run before the transition event is recorded
- state changes must not be written ad hoc outside transition execution
- if side effects fail, the failure must also be logged explicitly
- same-payload resets and payload-changing transitions must remain distinct

## End-to-End Business Workflow Ordering

Normal first-pass path:

1. ODK sync receives new or changed payload
2. consent is evaluated
3. invalid consent -> `consent_refused`
4. valid coding-eligible payload -> `smartva_pending`
5. SmartVA generated, regenerated, or failed-recorded for current payload
6. `ready_for_coding`
7. coder enters work through:
   - `random_form_allocation`, or
   - `pick_and_choose`
8. both entry modes converge on `coding_started`
9. `coding_in_progress`
10. coder may:
    - save partial work
    - save step 1
    - finalize COD
    - mark not codeable

Reset / recovery path:

1. coding allocation times out or is abandoned
2. determine whether this is first-pass or recode
3. first-pass reset -> `ready_for_coding`
4. recode reset -> `coder_finalized`
5. no SmartVA rerun for same-payload reset paths

Protected finalized path:

1. submission is in protected finalized state
2. upstream ODK payload changes
3. durable upstream-change event and notifications are created
4. submission enters `finalized_upstream_changed`
5. data manager or admin resolves:
   - accept -> `smartva_pending`
   - reject -> `coder_finalized`

Admin/recode path:

1. authoritative final COD exists
2. recode or override trigger occurs within allowed rules
3. same-payload override/recode re-enters coding path without SmartVA rerun
4. replacement final COD may supersede prior authority

Reviewer path:

1. submission is `coder_finalized`
2. 24-hour coder recode window expires
3. submission enters `reviewer_eligible`
4. optional sampling/selection determines whether reviewer coding begins
5. reviewer final COD, if submitted, supersedes coder final COD authority

## Detailed Implementation Plan

### Phase 1: Folder Cut and Compatibility Shims

Goal:
- centralize workflow code under `app/services/workflow/`

Steps:
- create workflow package files
- move current in-progress workflow modules into the package
- keep thin compatibility wrappers at old import paths during the migration
- do not broaden behavior in this phase

Acceptance:
- imports continue to resolve
- no runtime behavior change beyond module path cleanup

### Phase 2: Centralize Direct State Writes

Goal:
- stop ad hoc calls to `set_submission_workflow_state(...)`

Steps:
- identify all direct writers in:
  - `app/services/va_data_sync/va_data_sync_01_odkcentral.py`
  - `app/services/smartva_service.py`
  - `app/services/coding_allocation_service.py`
  - `app/services/coder_workflow_service.py`
  - `app/services/data_management_service.py`
  - `app/routes/va_form.py`
- replace each write with named transition helpers from
  `app/services/workflow/transitions.py`
- keep `state_store.py` as the only low-level persistence layer
- ensure transition helpers emit both:
  - durable audit/event records
  - structured application log messages

Acceptance:
- runtime callers use named transitions rather than raw state strings
- direct writes remain only in `state_store.py`
- every transition is traceable by event id/reason in logs and DB audit history

### Phase 3: Separate Intake Mode from Workflow State

Goal:
- make the random vs pick distinction explicit only at the allocation boundary

Steps:
- keep `random_form_allocation` and `pick_and_choose` logic in
  `workflow/intake_modes.py`
- ensure both entry modes call the same `coding_started` transition
- document clearly that intake mode is project configuration, not a submission
  state

Acceptance:
- allocation behavior differs by project mode
- state machine does not branch on intake mode after coding starts

### Phase 4: Durable Protected Upstream Change Handling

Goal:
- close the documented upstream-change durability gaps

Steps:
- add migrations for:
  - `va_submission_upstream_changes`
  - `va_submission_notifications`
- on protected sync change:
  - snapshot previous payload
  - store incoming payload
  - store previous authoritative final assessment link
  - create pending admin/data-manager notifications
- on accept/reject:
  - resolve pending upstream-change event
  - resolve notifications
  - clear or preserve authoritative final COD appropriately

Acceptance:
- no protected upstream change is only implicit in audit logs
- old payload and preserved COD linkage are queryable

### Phase 5: SmartVA Gate Completion

Goal:
- finish the SmartVA prerequisite model cleanly

Steps:
- keep `smartva_pending` for new/changed payloads only
- do not rerun SmartVA for same-payload timeout/demo/admin resets
- add explicit failure-recording path so failed SmartVA attempts can still
  advance to `ready_for_coding` with a durable record

Acceptance:
- `ready_for_coding` means SmartVA generated, regenerated, or failed-recorded
  for the current payload

Status:
- completed in runtime
- `smartva_pending` is now the gate for new/changed payloads
- same-payload timeout/demo/admin resets do not rerun SmartVA
- SmartVA failure-recorded paths can advance the current payload to
  `ready_for_coding`

### Phase 6: Recode and Admin Override Normalization

Goal:
- make recode and override behavior explicit transitions instead of scattered
  service-side effects

Steps:
- define recode transitions and guards
- define admin override transition
- ensure same-payload override returns to coding-ready path without SmartVA
  rerun
- preserve authoritative final COD until replacement final COD is submitted

Acceptance:
- recode behavior is explicit and non-destructive
- override path is distinct from upstream-change path

Status:
- completed in runtime
- recode start/finalization now use explicit transitions
- admin override uses an explicit workflow transition and remains global-admin
  only per current access-control policy
- recode transitions require an active recode episode as a workflow guard

### Phase 7: Rename Legacy State Value

Goal:
- adopt the clearer target name after behavior is stable

Steps:
- migrate legacy `revoked_va_data_changed` rows and callers to
  `finalized_upstream_changed`
- keep UI label `Finalized - ODK Data Changed`
- add migration/backfill for stored rows
- update docs/tests/search labels

Acceptance:
- no remaining runtime references to the legacy `revoked_va_data_changed`

Status:
- completed in runtime and docs
- canonical current key is `finalized_upstream_changed`
- legacy `revoked_va_data_changed` remains historical only

### Phase 8: Retire Active `closed` Transition

Goal:
- retire `closed` from the active BPMN while preserving legacy compatibility

Steps:
- move the post-24h resting path to `reviewer_eligible`
- keep `closed` only as a legacy compatibility/protected state for old rows
- remove active workflow/API/docs assumptions that ordinary cases terminate in
  `closed`

Acceptance:
- active workflow no longer depends on `closed`
- `reviewer_eligible` is the durable post-24h resting state
- `closed` is documented as legacy compatibility only

Status:
- completed in runtime and docs
- the hourly coding-maintenance path now writes `reviewer_eligible`
- `closed` remains defined only for compatibility/protection of historical rows

## Schema and Migration Work

Required additive migrations:

1. `va_submission_upstream_changes`
2. `va_submission_notifications`
3. rename/backfill for legacy `revoked_va_data_changed`
4. future optional SmartVA failure-record table if current schema cannot model
   failure per payload cleanly

Migration rules:

- additive first
- no destructive rewrite of existing workflow rows
- preserve current audit trail
- do not require DB reset

## Testing Plan

Add or update focused tests for:

- sync routes new payloads to `smartva_pending`
- SmartVA completion moves `smartva_pending -> ready_for_coding`
- timeout cleanup returns same-payload first-pass cases to `ready_for_coding`
- recode timeout returns to `coder_finalized`
- random allocation and pick-and-choose both use the same coding-start
  transition
- protected upstream-change sync creates durable event + notifications
- accept-upstream-change moves to `smartva_pending` and clears authoritative COD
- reject-upstream-change returns to `coder_finalized`
- data-manager Not Codeable uses transition service
- coder step1/final/not-codeable use transition service

Likely test files:

- `tests/services/test_odk_sync_service.py`
- `tests/services/test_odk_sync_workflow_guards.py`
- `tests/services/test_smartva_service.py`
- `tests/services/test_data_management_service.py`
- `tests/services/test_submission_workflow_service.py`
- `tests/services/test_coding_allocation_service.py`
- `tests/routes/test_pick_and_choose_coding.py`
- route tests covering `app/routes/va_form.py`

## Documentation Plan

Update in lockstep with implementation:

- `docs/policy/coding-workflow-state-machine.md`
- `docs/policy/odk-sync-policy.md`
- `docs/policy/smartva-generation-policy.md`
- `docs/current-state/workflow-and-permissions.md`
- `docs/current-state/odk-sync.md`
- `docs/planning/coding-workflow-state-machine-migration.md`
- `docs/planning/finalized-upstream-change-gap-plan.md`

Docs must always separate:

- current implemented runtime behavior
- desired target behavior
- remaining plan/gaps

## Resolved Policy Decisions

These items are no longer open questions for the refactor:

1. `screening_pending` is optional and controlled at the project level.
2. upstream-change accept/reject authority is `data_manager-plus-admin`.
3. `closed` must become a real runtime state.
4. legacy `revoked_va_data_changed` must be migrated to
   `finalized_upstream_changed`.

## State Ownership

Ownership must be explicit.

1. `workflow/definition.py`
   owns canonical workflow-state names and transition ids.
2. `workflow/state_store.py`
   owns canonical workflow-state persistence and legacy fallback inference.
3. `workflow/transitions.py`
   owns business transition entrypoints and transition event logging.
4. `workflow/upstream_changes.py`
   owns durable upstream-change subprocess records and resolution state.
5. routes, sync code, SmartVA code, and cleanup jobs
   may trigger transitions, but must not write workflow state directly.

Forbidden outside the workflow package:

- raw workflow state string literals for writes
- direct calls to canonical state persistence helpers from routes
- ad hoc transition semantics embedded in unrelated services

## Transaction Boundaries

The refactor must define transaction boundaries deliberately.

In-transaction work for a transition:

1. load current submission workflow state
2. validate transition guard
3. write workflow event log entry
4. write canonical workflow state change
5. write directly-coupled side effects that must stay atomic with the state
   change
6. commit

Examples of directly-coupled side effects:

- allocation activation/deactivation
- final COD authority pointer updates
- upstream-change event resolution rows
- notification row creation or resolution

After-commit or separable work:

- external ODK calls when they are best-effort
- derived dashboard refresh jobs
- non-critical notifications

If a post-commit side effect fails:

- log explicit failure event
- do not silently roll back the already-committed business transition
- enqueue or document retry behavior where needed

## Idempotency Rules

Every high-risk transition path must be safe to repeat.

Rules:

1. sync with unchanged payload must not create duplicate business transitions
2. protected upstream-change detection must update the pending change record,
   not create uncontrolled duplicates
3. repeated SmartVA completion callbacks for the same payload must not create
   multiple state advancements
4. repeated accept or reject actions on an already resolved upstream change
   must be rejected cleanly
5. repeated timeout cleanup must not oscillate state or duplicate audit rows
   excessively
6. duplicate coder final submit POSTs must not create multiple authoritative
   final COD records for the same intent without clear supersession

## Concurrency Rules

Concurrent actors must be handled explicitly.

Scenarios:

1. sync updates a submission while a coder is actively saving work
2. two admins/data managers try to resolve the same upstream-change event
3. timeout cleanup runs while a coder resumes allocation
4. SmartVA completion races with manual admin/data-manager action

Required strategy:

- use current-state checks in transitions
- prefer row-level locking or optimistic conflict rejection on the critical
  resolution rows
- never let a later side effect silently overwrite a more recent transition
- produce explicit conflict/error logging for rejected concurrent actions

## Event Taxonomy

The event model should distinguish between three classes:

1. transition events
   - canonical business-state change events
   - emitted by `workflow/transitions.py`
2. domain side-effect events
   - allocation created/released
   - authority repointed
   - SmartVA result created/deactivated
   - upstream-change snapshot created/resolved
3. operational events
   - retries
   - warnings
   - external system failures

Naming convention:

- transition ids remain snake_case and business-specific
- side-effect event names should include the domain object
- application log messages should always include `va_sid`

## State Entry and Exit Criteria

Entry/exit criteria must be defined for each major state.

### `screening_pending`

Entry:

- consent valid
- project configuration requires screening before SmartVA

Exit:

- screening pass -> `smartva_pending`
- screening reject -> `not_codeable_by_data_manager`

### `smartva_pending`

Entry:

- new or payload-changed submission eligible for coding
- screening passed, or screening bypassed by project config

Exit:

- SmartVA generated -> `ready_for_coding`
- SmartVA regenerated -> `ready_for_coding`
- SmartVA failed-recorded -> `ready_for_coding`

### `ready_for_coding`

Entry:

- current payload has undergone SmartVA attempt
- no active coding allocation
- submission is not excluded by data-manager/coder/protected states

Exit:

- coder random allocation start -> `coding_in_progress`
- coder pick-and-choose start -> `coding_in_progress`
- data-manager exclusion -> `not_codeable_by_data_manager`

### `coder_finalized`

Entry:

- final COD submitted and active
- allocation released
- authority updated

Exit:

- accepted upstream payload change path -> `finalized_upstream_changed`
- admin override/recode path -> coding path
- recode window expiry -> `reviewer_eligible`

### `finalized_upstream_changed`

Entry:

- submission was protected/finalized
- upstream ODK payload changed
- durable upstream-change event exists

Exit:

- accept -> `smartva_pending`
- reject -> `coder_finalized`

### `closed` (legacy compatibility only)

Entry:
- only for historical rows written before the active workflow retired this
  state

Exit:

- no active BPMN entry or exit rules; if encountered it remains protected

## Failure Semantics

Failure handling must be explicit, not implied.

1. SmartVA processing failure
   - persist failure-recorded event for current payload
   - allow controlled advancement to `ready_for_coding`
2. ODK comment/review-state push failure
   - do not roll back local business decision
   - log failure clearly
3. notification creation failure
   - if notification is mandatory for the transition, keep it in-transaction
   - otherwise log and retry later
4. audit/event-log write failure
   - transition must fail if required durable workflow event cannot be written
5. side-effect partial failure
   - emit explicit failure event and avoid silent partial completion

## Authorization Matrix

Each transition must have explicit actor permissions.

System:

- sync routing
- SmartVA completion/failure-recording
- timeout cleanup
- demo retention cleanup
- close-after-recode-window-expiry

Coder:

- coding start
- step 1 save
- final COD submit
- coder not-codeable
- recode start within allowed rules

Data Manager:

- screening reject
- upstream-change accept
- upstream-change reject

Admin:

- all data-manager transition powers
- demo start/reset
- optional override/recode actions
- close-policy administration if needed

Reviewer:

- reviewer is not QA approval/rejection in the target model
- reviewer is an optional delayed secondary-coding actor
- reviewer eligibility starts only after the coder's 24-hour recode window
  closes
- reviewer final COD must be modeled as a distinct artifact and may supersede
  coder final COD authority
- legacy `va_reviewer_review` should not be repurposed as reviewer final COD
- additive reviewer final-COD storage now exists in
  `va_reviewer_final_assessments`; transition wiring and authority cutover are
  still pending
- reviewer workflow now has runtime transition/service support for:
  - `reviewer_coding_in_progress`
  - `reviewer_finalized`
- `va_final_cod_authority` now has reviewer-pointer support
- remaining reviewer gap is downstream reader cutover across analytics/reporting

## Legacy Cutover Rules

The system is still in migration and must be explicit about that.

Rules:

1. canonical submission workflow state lives in `va_submission_workflow`
2. some fallback state inference from legacy active artifact rows remains during
   migration
3. fallback inference should be isolated to `workflow/state_store.py`
4. no new business logic should depend on legacy inference outside that layer
5. legacy inference can be removed only after all active writers and all major
   readers use canonical transitions/state

Cutover completion criteria:

- all state writers use `workflow/transitions.py`
- dashboards and allocation readers use canonical state
- protected upstream-change behavior uses durable subprocess rows

## Observability and Metrics

The workflow package should support operational visibility.

Required metrics or queries:

1. submission counts by canonical workflow state
2. count of stuck `smartva_pending`
3. count of stuck `finalized_upstream_changed`
4. transition failure counts by transition id
5. average time spent in:
   - `smartva_pending`
   - `ready_for_coding`
   - `coding_in_progress`
   - `coder_finalized`
6. unresolved upstream-change event count

At minimum, logs and durable events must make these queries possible even if
dedicated dashboards come later.

## Migration Sequence

Implementation should land in this order:

1. create workflow package structure
2. cut imports to the workflow package
3. centralize active state writers into transition helpers
4. add additive schema for durable upstream-change records
5. migrate legacy `revoked_va_data_changed` to `finalized_upstream_changed`
6. add SmartVA failure-recorded path
7. retire active `closed` semantics while preserving compatibility handling
8. remove obsolete legacy paths once readers and writers are cut over

Deployment/migration rules:

- additive schema first
- then code using new schema
- then backfill/rename data
- then remove obsolete paths

Rollback rule:

- each slice should remain reversible until the final cleanup slice

## References

- `docs/policy/coding-workflow-state-machine.md`
- `docs/policy/odk-sync-policy.md`
- `docs/policy/smartva-generation-policy.md`
- `docs/current-state/workflow-and-permissions.md`
- `app/services/va_data_sync/va_data_sync_01_odkcentral.py`
- `app/services/smartva_service.py`
- `app/services/coder_workflow_service.py`
- `app/services/coding_allocation_service.py`
- `app/services/data_management_service.py`
- `app/routes/va_form.py`

## Expected Scope

This is a multi-slice architectural refactor. It should land in staged commits:

1. workflow package layout plus compatibility shims
2. transition-service cutover for active writers
3. upstream-change persistence plus migrations
4. SmartVA failure-recording completion
5. recode/admin override normalization
6. state rename and optional close implementation
