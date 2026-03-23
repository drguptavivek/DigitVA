---
title: "Plan: Coding Workflow State Machine Migration"
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-03-23
---

# Plan: Coding Workflow State Machine Migration

## Goal

Migrate the current coder/reviewer workflow from implicit, record-inference
behavior to the policy-defined state machine documented in:

- [Coding Workflow State Machine Policy](../policy/coding-workflow-state-machine.md)
- [Data Manager Workflow Policy](../policy/data-manager-workflow.md)
- [Final COD Authority Policy](../policy/final-cod-authority.md)
- [Not Codeable ODK Central Sync Policy](../policy/not-codeable-odk-central-sync.md)

## Current Implementation Gaps

### 1. No canonical submission workflow state

Current behavior infers workflow from the presence or absence of:

- `va_allocations`
- `va_initial_assessments`
- `va_final_assessments`
- `va_coder_review`
- `va_reviewer_review`

This does not provide a single authoritative business state such as:

- `ready_for_coding`
- `partial_coding_saved`
- `coder_finalized`
- `not_codeable_by_data_manager`

### 2. No project-level coding intake mode

Current coder workflow supports random allocation only.

Observed behavior:

- coder dashboard exposes `Start VA Coding`
- the app allocates a submission automatically from the eligible pool
- there is no project-level setting for `random_form_allocation` vs
  `pick_and_choose`
- there is no pick-and-choose browse/start workflow for coders

### 3. No data-manager role in the runtime model

Current grants and role helpers support:

- `admin`
- `project_pi`
- `site_pi`
- `collaborator`
- `coder`
- `reviewer`

Missing relative to policy:

- `data_manager` role in enums and grant validation
- project-scoped and project-site-scoped data-manager grants
- data-manager dashboard
- read-only submission view path for data managers
- data-manager-specific Not Codeable record and audit trail

### 4. No data-manager screening / exclusion path

Policy allows optional upstream screening and data-manager Not Codeable
exclusion.

Current implementation has no separate data-manager triage record.

As a result:

- a data-manager decision cannot be represented distinctly
- bad submissions cannot be excluded from coder allocation without using coder
  workflow objects incorrectly

### 5. Timeout cleanup does not implement state reversion

Current stale allocation cleanup:

- releases the coding allocation only
- preserves Step 1 coder work

Policy target for first-pass coding:

- incomplete first-pass coding episodes revert to `ready_for_coding`
- first-pass NQA and Social Autopsy delay analysis do not persist as completed
  artifacts after timeout reversion

### 6. Recode is currently destructive

Current `varecode` behavior deactivates active:

- initial assessment
- final assessment
- coder review

before the replacement coding is completed.

Policy target:

- recode is allowed only for coder-finalized cases inside the revision window
- previous finalized COD remains operative until a replacement finalized COD is
  successfully saved
- incomplete recode work must not replace the current finalized COD

### 7. Reviewer workflow is not yet implemented as delayed secondary coding

Policy now defines reviewer participation as:

- optional and sample-based
- a secondary coding path rather than accept/reject QA
- available only after the coder's 24-hour recode window closes

Current implementation now writes the post-window state `reviewer_eligible`,
and now also supports reviewer coding transitions plus reviewer final-COD
authority in the runtime core.

Important design note:

- the existing `va_reviewer_review` table is a legacy QA/review artifact
- it should not be reused as the reviewer final-COD store for the new model
- additive reviewer final-COD storage now exists in
  `va_reviewer_final_assessments`
- reviewer coding runtime now exists through dedicated service/API paths:
  - `reviewer_coding_in_progress`
  - `reviewer_finalized`
- reviewer final-COD authority now has service-level cutover support
- reviewer-aware analytics MV cutover is now implemented
- remaining work is legacy reader/reporting cleanup outside the analytics MV

### 8. Not Codeable pathways are not split by actor class

Current implementation supports coder Not Codeable only.

Policy requires two distinct terminal pathways:

- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

These must not share the same business record in a way that obscures actor
identity.

### 9. Coder dashboard and status reporting are still tied to old workflow rules

Current dashboard counts and filters are based on:

- active initial assessments
- active final assessments
- active coder reviews
- active allocations

They are not yet driven by canonical workflow state.

### 10. No explicit authoritative final-COD model

Current implementation infers final COD from active COD-related rows.

This is insufficient relative to policy because the system now needs to answer:

- which COD is currently authoritative for the submission
- whether a prior finalized COD has been superseded
- whether a reviewer override is now the operative final COD

Missing relative to policy:

- a single authoritative final-COD pointer or equivalent model
- supersession tracking for recode outcomes
- explicit override authority tracking for reviewer decisions
- reporting that consistently exposes only the authoritative final COD

### 11. SmartVA gating is only partially implemented

Current implementation now writes `smartva_pending` for newly synced and
payload-changed submissions, and successful SmartVA generation transitions those
submissions to `ready_for_coding`.

Remaining gaps:

- explicit SmartVA-failure recording is not yet implemented
- same-payload returns and changed-payload returns are not yet documented and
  enforced uniformly across every workflow entry path
- admin override versus upstream-change acceptance still needs a finalized
  state-machine cleanup pass

## Migration Strategy

### Phase 1. Introduce explicit workflow metadata

Add a canonical workflow-state model for submissions, without removing existing
tables yet.

This layer should:

- coexist with existing coder/reviewer records during transition
- be backfillable from current data
- become the new source for dashboard eligibility and status reporting

### Phase 2. Add project-level coding intake mode

Introduce a project-level setting:

- `random_form_allocation`
- `pick_and_choose`

Then update coder dashboard behavior to respect the configured mode.

### Phase 3. Add data-manager role and triage path

Implement:

- `data_manager` grants
- dashboard/list view
- read-only submission view
- data-manager Not Codeable record
- exclusion from coder allocation

### Phase 4. Align timeout cleanup with policy

Replace current allocation-only stale cleanup with explicit incomplete-episode
reversion for first-pass coding.

This phase must handle:

- first-pass NQA cleanup rules
- first-pass Social Autopsy delay cleanup rules
- audit logging of the reversion

### Phase 5. Make recode non-destructive

Change recode to preserve the currently finalized COD until replacement final
COD is successfully submitted.

This phase requires clear audit linkage between:

- original finalized coding
- recode episode
- superseding finalized coding

Current status:

- implemented
- recode now preserves the authoritative final COD until replacement final COD
  is submitted
- explicit recode workflow transitions are now used for start/finalization

### Phase 6. Add delayed reviewer secondary-coding workflow

Add explicit reviewer workflow states and transitions so optional sampled
reviewer coding can start only after a submission becomes
`reviewer_eligible`.

Current status:

- partially implemented
- `reviewer_eligible` now exists in runtime and is written by the hourly
  recode-window maintenance path
- reviewer start/finalization transitions and reviewer-owned final COD
  authority are not yet implemented

### Phase 7. Add explicit final-COD authority model

Introduce an explicit way to identify the authoritative final COD for each
submission.

This phase must handle:

- coder-finalized COD authority
- reviewer final-COD authority
- superseded finalized COD history
- reporting/export cutover to authoritative final COD only

### Phase 8. Complete SmartVA-gated coding readiness

Finish the SmartVA gate so workflow semantics are explicit and uniform:

- keep `smartva_pending` for new and changed payloads
- keep same-payload cleanup returns direct to `ready_for_coding`
- add explicit SmartVA-failure recording for the current payload
- align admin-override and upstream-change acceptance paths with the same rule
- keep coder allocation restricted to `ready_for_coding`

Current status:

- implemented for the current workflow core
- `smartva_pending` gates new/changed payloads
- same-payload cleanup returns do not rerun SmartVA
- `ready_for_coding` now means SmartVA was attempted for the current payload

Additional runtime note:

- `closed` remains defined only as a legacy compatibility state
- the hourly coding-maintenance path now lands on `reviewer_eligible` instead
  of writing `closed`

## Recommended Delivery Order

1. canonical workflow-state model
2. project-level intake mode
3. data-manager role and triage path
4. coder dashboard migration to canonical state
5. timeout reversion alignment
6. non-destructive recode
7. reviewer overlay state model
8. authoritative final-COD model
9. complete SmartVA-gated coding readiness
10. parity verification and cleanup

Current completion note:

- delivery order items 1, 2, 3, 4, 5, 6, 8, 9, and 10 are substantially
  complete in the current workflow runtime
- reviewer secondary-coding workflow remains the main workflow-design item
  still open, especially downstream reader/reporting parity

## Data Safety Notes

This migration affects live workflow data.

Required safeguards:

- additive schema changes first
- backfill before cutover
- preserve all historical coder/reviewer/Not Codeable records
- preserve all historical finalized COD records, including superseded ones
- do not delete legacy records during the first cutover
- keep audit history intact across every workflow transition

## Verification Focus

The migration should be verified against these scenarios:

- random coder intake project
- pick-and-choose project
- first-pass coder timeout
- coder Not Codeable with ODK Central success
- coder Not Codeable with ODK Central failure
- data-manager Not Codeable exclusion
- recode inside revision window
- incomplete recode not replacing prior final COD
- reviewer final over coder-finalized case
- authoritative final COD selection after recode
- authoritative final COD selection after reviewer finalization
