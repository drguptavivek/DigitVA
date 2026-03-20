---
title: Coding Workflow State Machine Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-20
---

# Coding Workflow State Machine Policy

## Purpose

DigitVA needs an explicit workflow state machine for submission handling so
that:

- coding progress is traceable
- partial work is distinguishable from completed work
- Not Codeable outcomes are explicit
- reviewer activity is modeled as optional parallel oversight
- data-manager triage does not masquerade as coder activity

This policy defines the intended workflow states and transition rules.

## Design Rule

Workflow state and allocation state are separate concerns.

- allocation answers: who is currently working on the case
- workflow state answers: where the case is in the business process

The system must not infer workflow completion only from allocation presence or
absence.

## Core Workflow Tracks

DigitVA operates three related but distinct tracks:

1. coder workflow
2. optional reviewer oversight workflow
3. optional data-manager triage workflow

Only the coder workflow is required for normal COD completion.

Reviewer activity is optional and may be initiated independently.

Data-manager triage is optional and acts as an upstream gating or exclusion
mechanism for problematic submissions.

## Coding Intake Mode

Each project must choose one coder-intake mode for normal coding operations.

Supported modes:

- `random_form_allocation`
- `pick_and_choose`

This is a project-level workflow choice.

The application must not assume that all projects use the same coder-intake
mode.

### `random_form_allocation`

In this mode:

- the coder does not choose from a browse list
- the system allocates one eligible submission from the project pool
- allocation is subject to all standard exclusions

Standard exclusions include:

- `not_codeable_by_data_manager`
- `not_codeable_by_coder`
- already finalized cases
- currently active allocations
- any other workflow-specific exclusion rules

### `pick_and_choose`

In this mode:

- the coder may browse the eligible submission list for the project
- the coder may view submission status before choosing work
- the coder may explicitly start coding any eligible submission in scope

The pick-and-choose list must still apply workflow exclusions.

That means a coder may browse and choose only from cases that are eligible for
coding under the project's workflow rules.

## Dashboard Implication

The coder dashboard behavior depends on the configured intake mode.

For `random_form_allocation`:

- the dashboard should present a start/resume coding flow
- the next case is assigned by the system

For `pick_and_choose`:

- the dashboard should present a browseable list of eligible submissions
- each eligible row may offer a start-coding action
- the coder may inspect status before deciding which case to open

The project-level intake mode affects only how coding work is entered. It does
not change the downstream coding state machine once a case enters active coder
workflow.

## Demo Coding Mode

DigitVA also supports an admin-only demo coding entry path through
`vademo_start_coding`.

Demo coding uses the same case-viewing and coding forms as normal coding, but
it is not a permanent production completion path.

Current intended baseline:

- demo coding may save NQA, Social Autopsy Analysis, and final COD artifacts
- those demo artifacts must be visible immediately after save, including on the
  coder dashboard while they remain active
- demo artifacts are temporary and must expire automatically after the
  configured demo-retention window
- after demo-retention cleanup, the submission must return to the non-demo
  workflow state implied by any remaining active records

The demo-retention rules are defined in
[Demo Coding Retention Policy](demo-coding-retention.md).

## Canonical Case State

The canonical submission-level workflow state should be modeled with one of the
following business states:

- `screening_pending`
- `smartva_pending`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved`
- `coder_finalized`
- `revoked_va_data_changed`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`
- `closed`

These states describe the local business outcome for the submission.

Target naming cleanup:

- current implemented state key: `revoked_va_data_changed`
- preferred future state key: `finalized_upstream_changed`
- preferred UI label: `Finalized - ODK Data Changed`

Current implementation note:

- `closed` is part of the desired state machine, but the current runtime does
  not yet implement any transition that writes `closed`
- `smartva_pending` is part of the desired state machine, but the current
  runtime still places consent-valid submissions directly into
  `ready_for_coding`
- until that transition exists, `closed` should be read as target-state policy,
  not current runtime behavior

## Protected States

The following states are **protected** from automatic data changes:

- `coder_finalized` — Final COD has been submitted; ODK sync and SmartVA blocked
- `revoked_va_data_changed` — Current implemented key for finalized cases whose upstream ODK data changed; pending resolution
- `closed` — Terminal target state; no further changes permitted once implemented

See [ODK Sync Policy](odk-sync-policy.md) and [SmartVA Generation Policy](smartva-generation-policy.md) for details.

## ASCII Flowchart

Desired target state machine:

```text
                           +----------------------+
                           |  screening_pending   |
                           +----------+-----------+
                                      |
                     data manager     | pass / no flag
                     may inspect      v
                           +----------------------+
                           |    smartva_pending   |
                           +----------+-----------+
                                      |
                                      | SmartVA generated,
                                      | regenerated, or
                                      | failed-recorded
                                      v
                           +----------------------+
                           |   ready_for_coding   |
                           +----------+-----------+
                                      |
                                      | random coder allocation
                                      v
                           +----------------------+
                           |  coding_in_progress  |
                           +----+-----------+-----+
                                |           |
                     partial    |           | Step 1 COD saved
                     save       |           v
                                |   +----------------------+
                                +-> | partial_coding_saved |
                                |   +----------+-----------+
                                |              |
                                |              | resume / continue
                                |              v
                                |   +----------------------+
                                |   |  coder_step1_saved   |
                                |   +----------+-----------+
                                |              |
                                |              | final COD submitted
                                |              v
                                |   +----------------------+
                                |   |   coder_finalized    |  <-- PROTECTED STATE
                                |   +----------+-----------+
                                |              |
                                |              +-------------------------+
                                |              |                         |
                                |              | recode window expires   | upstream ODK data changed
                                |              | automatically           | (automatic during sync)
                                |              v                         v
                                |        +-----------+        +---------------------------+
                                |        |  closed   |        | revoked_va_data_changed   | <-- PROTECTED STATE
                                |        +-----------+        +-------------+-------------+
                                |                                           |
                                |                                           | admin accepts change
                                |                                           | (recode required)
                                |                                           v
                                |                                     +------------------+
                                |                                     | ready_for_coding |
                                |                                     +------------------+
                                |
                                | mark Not Codeable
                                v
                     +---------------------------+
                     |   not_codeable_by_coder   |
                     +-------------+-------------+
                                   |
                                   | local save + ODK hasIssues sync
                                   v
                             +-----------+
                             |  closed   |
                             +-----------+


  Allocation timeout / abandonment:

    coding_in_progress -----+
                            |
    partial_coding_saved ---+---- stale allocation cleanup ----> ready_for_coding
                            |
    coder_step1_saved ------+

    Notes:
    - incomplete coding episode is reverted
    - first-pass coding does not preserve NQA as a completed artifact after
      timeout reversion
    - first-pass coding does not preserve Social Autopsy delay analysis as a
      completed artifact after timeout reversion


  Demo coding retention expiry:

    coder_finalized ----- demo retention cleanup ----> ready_for_coding

    Notes:
    - applies only to artifacts created through `vademo_start_coding`
    - finalized demo artifacts may remain visible for the configured retention
      window before cleanup
    - cleanup must also deactivate demo NQA and Social Autopsy artifacts tied
      to the same completed demo coding outcome


  Upstream data change for finalized submission:

    coder_finalized ----- ODK data changed -----> revoked_va_data_changed

    Target naming cleanup:

    coder_finalized ----- ODK data changed -----> finalized_upstream_changed

    Notes:
    - ODK is source of truth, but finalized COD is protected
    - Current implementation preserves active coding artifacts and writes audit logs
    - Historical COD linkage, VA payload snapshotting, and notification artifacts are still incomplete
    - Requires manual intervention to resolve
    - SmartVA NOT regenerated automatically
    - See ODK Sync Policy for full details


  Optional admin override:

    coder_finalized ----- admin overrides final COD -----> ready_for_coding

    Notes:
    - this is separate from upstream ODK-change handling
    - this returns the case to the normal coding-ready queue


  Optional data-manager triage:

    screening_pending or ready_for_coding
                   |
                   | data manager marks not codeable
                   v
      +-------------------------------+
      | not_codeable_by_data_manager  |
      +---------------+---------------+
                      |
                      | excluded from automatic coder allocation pool
                      v
                +-----------+
                |  closed   |
                +-----------+


  Optional reviewer oversight (parallel, not mandatory mainline state):

      coder_finalized
            |
            | reviewer initiates review
            v
      +------------------+
      |   under_review   |
      +----+--------+----+
           |        |
           |        | reviewer overrides
           |        v
           |   +-------------------+
           |   | override_recorded |
           |   +-------------------+
           |
           | review completed without override
           v
      +------------------+
      | review_complete  |
      +------------------+
```

Current implementation note:

- the runtime currently writes `revoked_va_data_changed`, but does not yet
  transition any submission into `closed`
- the runtime also does not yet write `smartva_pending`; consent-valid cases
  currently go directly to `ready_for_coding`
- the `smartva_pending` and `closed` branches in the diagram therefore represent desired target
  behavior, not current runtime behavior

## Data Manager Workflow

Data-manager workflow is optional and separate from coder activity.

### Screening

Newly synced or newly eligible cases may be treated as `screening_pending` if
the deployment enables data-manager screening before coding.

Screening is optional.

If a case is not screened, it may move into `smartva_pending`.

### SmartVA Gate

`screening_pending` or newly eligible case -> `smartva_pending`

This state means the submission is eligible for coding workflow, but must not
be released to coders until SmartVA has been attempted for the current payload.

`smartva_pending` -> `ready_for_coding`

This transition happens only after one of these outcomes is recorded for the
current submission payload:

- SmartVA was generated
- SmartVA was regenerated
- SmartVA explicitly failed and that failure was recorded for the current
  payload

Design rule:

- every path that newly enters or re-enters `ready_for_coding` must first pass
  through the SmartVA gate again for the current payload
- `ready_for_coding` therefore means the current payload has already undergone a
  SmartVA attempt, not merely that the submission is synced and consent-valid

### Data-manager Not Codeable

`screening_pending`, `smartva_pending`, or `ready_for_coding` ->
`not_codeable_by_data_manager`

This state means the submission is blocked from coder allocation because of a
data-quality or operational issue discovered by a data manager.

This outcome must:

- be stored as a data-manager-specific record
- not reuse coder-owned workflow records
- be auditable as a data-manager action

### Effect on coder allocation

Any case in `not_codeable_by_data_manager` must be excluded from the automatic
coder allocation pool until that state is explicitly cleared by a future
authorized workflow.

## Coder Workflow

### Entry

`ready_for_coding` -> `coding_in_progress`

Triggered when a coder starts coding and receives an allocation.

Precondition for `ready_for_coding`:

- SmartVA was generated for the current payload, or
- SmartVA was regenerated for the current payload, or
- SmartVA failed for the current payload and that failure was explicitly
  recorded

Coder entry into this state depends on the configured intake mode:

- `random_form_allocation`: system assigns a case from the available coding pool
- `pick_and_choose`: coder explicitly selects an eligible case from the browse
  list

### Partial save

`coding_in_progress` -> `partial_coding_saved`

Partial coding means the coder has begun work but has not yet completed COD.

Partial save must:

- preserve the coder's work within the active coding episode
- keep the case resumable during the active allocation window
- not count as finalized

### Step 1 COD

`coding_in_progress` or `partial_coding_saved` -> `coder_step1_saved`

This corresponds to initial COD assessment being saved locally.

Saving Step 1:

- must preserve the case as resumable during the active allocation window
- must not close the case
- must not count as completed coding

### Final coder outcome

`coder_step1_saved` -> `coder_finalized`

This transition happens only when the final COD step is successfully submitted.

Coder finalization must:

- keep the full audit history of Step 1 and Step 2
- release the active coding allocation
- mark the case as complete from the coder workflow perspective

### Coder Not Codeable

`coding_in_progress`, `partial_coding_saved`, or `coder_step1_saved` ->
`not_codeable_by_coder`

This is a terminal coder outcome.

It requires:

- a structured reason
- optional details where relevant
- local audit logging
- a best-effort upstream ODK Central update to `hasIssues`

Any case in `not_codeable_by_coder` must be excluded from the automatic coder
allocation pool.

### Not coded / partial coded reversion

If a coder does not complete the case within the active allocation window, the
case must revert out of the incomplete coding episode and return to
`ready_for_coding`.

This reversion applies to:

- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved` when final COD has not been submitted

The reversion must:

- release the active coding allocation
- return the case to `ready_for_coding`
- keep the prior incomplete episode auditable

For first-pass coding, supporting artifacts do not persist as completed
artifacts after timeout reversion.

That means:

- Narrative Quality Assessment does not persist through initial-coding timeout
  reversion
- Social Autopsy delay analysis does not persist through initial-coding timeout
  reversion

## Recode Window

Only coder-finalized cases may be recoded.

During the configured recode window:

- a coder-finalized case may be reopened for recode
- the existing finalized COD remains the operative result until a replacement
  finalized COD is saved
- incomplete recode work must not replace the existing finalized COD

Supporting artifacts behave differently during recode:

- Narrative Quality Assessment persists across recode attempts
- Social Autopsy delay analysis persists across recode attempts

These supporting artifacts may be updated independently even when the VA code is
not re-saved during recode.

The system must preserve auditability across:

- original coding
- resumed coding
- recode attempts
- superseded outcomes

Current implementation gap:

- the recode window exists as a business rule for reopening/recode eligibility
- but expiry of that window does not currently auto-transition submissions to
  `closed`
- that auto-close behavior remains target-state work

## Upstream Data Change (`revoked_va_data_changed` / target `finalized_upstream_changed`)

When ODK submission data changes for a `coder_finalized` submission, the system
must NOT automatically destroy the finalized COD or reset the workflow state.

### State Transition

Current implemented transition:

`coder_finalized` -> `revoked_va_data_changed`

Preferred target naming:

`coder_finalized` -> `finalized_upstream_changed`

This transition occurs automatically during ODK sync when:
- The submission exists in `coder_finalized` state
- ODK reports `updatedAt` newer than the local `va_odk_updatedat`
- The sync is NOT running with admin `force=True` override

### What Must Be Preserved

| Artifact | Preservation Method |
|---|---|
| Final COD | Current implementation keeps existing final assessment rows active; explicit preserved-link model still needed |
| VA data snapshot | Gap: current implementation overwrites `va_submissions.va_data` without a dedicated pre-update snapshot |
| Audit trail | Implemented via `VaSubmissionsAuditlog` and workflow-state audit entries |
| SmartVA result | Protected from automatic regeneration while in this protected state |

### Notification Requirements

When this transition occurs:

1. Dashboard visibility is implemented through the dedicated protected-state queue/filter
2. Immediate notification artifacts for data managers/admins are still a gap
3. Notification content requirements remain a target-state requirement

### Resolution Pathways

| Action | Outcome |
|---|---|
| Accept upstream change | Transition to `smartva_pending`, rerun SmartVA for the new ODK data, and return to `ready_for_coding` only after generate/regenerate/failure-recording |
| Reject upstream change | Restore to `coder_finalized`, keep current COD authoritative |
| Admin override final COD | Transition from `coder_finalized` to `smartva_pending`; rerun SmartVA for the current payload and return to `ready_for_coding` only after generate/regenerate/failure-recording |

Policy target: only admins can resolve finalized-upstream-change submissions.

Current implementation gap: data managers can currently perform accept/reject actions.

### Authorization

| Operation | Coder | Data Manager | Admin |
|---|---|---|---|
| View revoked submissions | No | Yes (scoped) | Yes |
| Accept upstream change | No | Current implementation: Yes | Policy target: Yes (Admin only) |
| Reject upstream change | No | Current implementation: Yes | Policy target: Yes (Admin only) |

## Reviewer Oversight Workflow

Reviewer workflow is optional and parallel.

It must not be treated as a mandatory successor stage for every
coder-finalized case.

Review may be initiated by:

- random selection
- browse-list selection
- filtered search and manual pick

### Reviewer precondition

Only cases already in `coder_finalized` should normally enter reviewer
oversight.

### Reviewer activity model

Reviewer activity should be modeled separately from the canonical coder state.

Recommended reviewer statuses:

- `not_reviewed`
- `under_review`
- `review_complete`
- `override_recorded`
- `returned_for_revision`

### Reviewer override

Reviewer override does not erase coder history.

Instead it must:

- preserve the coder decision as historical record
- create a distinct reviewer decision record
- make the override auditable

Reviewer activity is an overlay on top of coder completion, not a replacement
for the core coder workflow state machine.

## Allocation Rules

Allocations are transient reservations and do not define business completion.

Rules:

- an active coding allocation may exist only for cases in coder-working states
- stale allocation cleanup must release the allocation without discarding saved
  supporting artifacts
- allocation release alone must not mark a case complete

## Audit Expectations

Important milestones that must remain visible:

- screening started or passed, if screening is enabled
- data manager marked Not Codeable
- coding started
- partial coding saved
- Step 1 COD saved
- final COD submitted
- coder marked Not Codeable
- reviewer review started
- reviewer override recorded
- stale allocation released

## Completion Rule

A case is considered locally complete when one of these business outcomes is
true:

- `coder_finalized`
- `revoked_va_data_changed` (pending resolution; target name `finalized_upstream_changed`)
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

Target-state addition once implemented:

- `closed`

Reviewer activity may happen later, but it does not determine whether the core
coder workflow was completed.

## Related Documents

- [ODK Sync Policy](odk-sync-policy.md) — how sync interacts with workflow states
- [SmartVA Generation Policy](smartva-generation-policy.md) — when SmartVA runs
- [Final COD Authority Policy](final-cod-authority.md) — authoritative COD management
