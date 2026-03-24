---
title: Coding Workflow State Machine Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-24
---

# Coding Workflow State Machine Policy

## Purpose

DigitVA needs an explicit workflow state machine for submission handling so
that:

- coding progress is traceable
- partial work is distinguishable from completed work
- Not Codeable outcomes are explicit
- reviewer activity is modeled as optional delayed secondary coding
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
2. optional reviewer coding workflow
3. optional data-manager triage workflow

Only the coder workflow is required for normal COD completion.

Reviewer activity is optional and applies only to a selected subset of cases.

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

- `consent_refused` — submission synced from ODK but consent is absent or
  explicitly refused; stored in full but excluded from coding queue; ODK
  updates flow freely so consent corrections are picked up automatically
- `screening_pending`
- `smartva_pending`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved` (legacy compatibility only; current runtime does not
  create new entries in this state)
- `coder_step1_saved`
- `coder_finalized`
- `reviewer_eligible`
- `reviewer_coding_in_progress`
- `reviewer_finalized`
- `finalized_upstream_changed`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

These states describe the local business outcome for the submission.

`consent_refused` is a storage state only. Submissions in this state are
synced identically to all other submissions. They are excluded from coding
allocation, SmartVA generation, and all coding-queue counts. If ODK data is
updated and consent becomes valid, the next sync automatically transitions
the submission into `smartva_pending`.

Current naming:

- current persisted key: `finalized_upstream_changed`
- legacy migrated key: `revoked_va_data_changed`
- UI label: `Finalized - ODK Data Changed`

Current implementation note:

- current runtime now writes `reviewer_eligible` after coder recode-window
  expiry
- reviewer selection remains optional and open-ended; there is no active
  runtime terminal close endpoint for ordinary cases
- `screening_pending` is now supported as an optional project-configured gate
  with explicit pass/reject transitions
- `smartva_pending` is now written in current runtime for newly synced and
  payload-changed consent-valid submissions

Legacy compatibility note:

- `closed` remains defined as a legacy compatibility state for historical rows
  and protection logic
- it is not part of the active target BPMN for normal ongoing case handling

## Protected States

The following states are **protected** from automatic ODK data changes:

- `coder_finalized` — Final COD has been submitted; ODK sync and SmartVA blocked
- `reviewer_eligible` — Coder recode window has closed; waiting for optional
  reviewer-coding selection
- `reviewer_coding_in_progress` — Reviewer has an active mid-session allocation;
  ODK data change requires DM accept/reject rather than automatic re-routing,
  which would orphan the reviewer's active allocation
- `reviewer_finalized` — Reviewer has submitted a reviewer-owned final COD
- `finalized_upstream_changed` — Finalized cases whose upstream ODK data
  changed; pending resolution
- `closed` — legacy compatibility only; if old rows exist they remain protected

`consent_refused` is **not** protected. ODK updates flow freely so that consent
corrections are picked up automatically.

`not_codeable_by_coder` and `not_codeable_by_data_manager` are **not**
protected. If ODK data changes for an excluded case, the exclusion artifact is
deactivated and the case re-enters the workflow at `smartva_pending`. The
responsible DM or coder may re-exclude after reviewing the updated payload.

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
                               +------+------+
                               |             |
                               | random      | pick-and-choose
                               | allocation  | start selected form
                               v             v
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
                                |              | via hourly maintenance  | (automatic during sync)
                                |              v                         v
                                |        +--------------------+ +---------------------------+
                                |        | reviewer_eligible  | | finalized_upstream_changed| <-- PROTECTED STATE
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

    Notes:
    - local save + ODK hasIssues sync
    - coder not-codeable is itself the resting exclusion state


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
    - this uses the existing `admin` role semantics from the access-control
      policy
    - current policy defines `admin` as global-only, not project- or
      site-scoped


  Optional data-manager triage:

    screening_pending or ready_for_coding
                   |
                   | data manager marks not codeable
                   v
      +-------------------------------+
      | not_codeable_by_data_manager  |
      +---------------+---------------+

    Notes:
    - excluded from automatic coder allocation pool
    - data-manager not-codeable is itself the resting exclusion state


  Optional reviewer coding (sample-based, after coder recode window):

      coder_finalized
            |
            | 24h coder recode window closes
            v
      +--------------------+
      | reviewer_eligible  |
      +----+-----------+---+
           |           |
           | not in sample / no reviewer action yet
           | remain reviewer_eligible
           |
           | selected for reviewer coding
           v
      +--------------------------+
      | reviewer_coding_in_      |
      | progress                 |
      +------------+-------------+
                   |
                   | reviewer final COD submitted
                   v
             +----------------------+
             |  reviewer_finalized  |
             +----------------------+
```

Current implementation note:

- the runtime currently writes both `finalized_upstream_changed` and
  `reviewer_eligible`
- the runtime now also writes:
  - `reviewer_coding_in_progress`
  - `reviewer_finalized`
- the runtime now writes `smartva_pending` for newly synced and payload-changed
  consent-valid submissions
- screening-enabled projects may explicitly transition
  `screening_pending -> smartva_pending` or
  `screening_pending -> not_codeable_by_data_manager`
- reviewer delayed secondary coding is now partially modeled in runtime
- `reviewer_eligible` is now current runtime behavior for the post-24-hour
  timer path
- reviewer final-COD authority now prefers reviewer-owned final COD over coder
  final COD in the authority service
- active runtime does not use `closed` as a normal terminal state

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

- every path that introduces a new payload or changed payload into the coding
  queue must first pass through the SmartVA gate for that payload
- same-payload workflow returns, such as timeout cleanup or demo-retention
  cleanup, do not require a fresh SmartVA rerun
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
- and expiry of that window now transitions submissions to `reviewer_eligible`
- the active BPMN no longer relies on an automatic `closed` transition

## Upstream Data Change (`finalized_upstream_changed`)

When ODK submission data changes for a `coder_finalized` submission, the system
must NOT automatically destroy the finalized COD or reset the workflow state.

### State Transition

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
| Audit trail | Implemented via canonical `va_submission_workflow_events`; `VaSubmissionsAuditlog` remains for non-workflow operational audit |
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
| Admin override final COD | Transition from `coder_finalized` to `ready_for_coding` for recoding against the same payload; no SmartVA rerun required unless the payload has changed |

Policy baseline: data managers and admins may resolve
`finalized_upstream_changed` submissions.

### Authorization

| Operation | Coder | Data Manager | Admin |
|---|---|---|---|
| View upstream-changed submissions | No | Yes (scoped) | Yes |
| Accept upstream change | No | Yes (scoped) | Yes |
| Reject upstream change | No | Yes (scoped) | Yes |

## Reviewer Oversight Workflow

Reviewer workflow is optional and parallel.

It must not be treated as a mandatory successor stage for every
coder-finalized case.

Reviewer coding may be initiated by:

- random selection
- browse-list selection of a reviewer sample
- filtered search and manual pick of a reviewer sample

### Reviewer precondition

Reviewer coding must not overlap with the coder's 24-hour recode window.

Only cases that have:

- reached `coder_finalized`
- completed the 24-hour coder recode window
- not been reset back into the coder pool by admin

should become `reviewer_eligible`.

### Reviewer activity model

Reviewer is not an accept/reject QA overlay.

Reviewer is an optional secondary coding path with its own COD submission.

Reviewer workflow states:

- `reviewer_eligible`
- `reviewer_coding_in_progress`
- `reviewer_finalized`

There is no `not_selected_for_reviewer` state. Cases that are never selected
for reviewer coding simply remain in `reviewer_eligible` indefinitely. An
explicit exclusion state for reviewer sampling is not part of the current
runtime and should not be added until a reviewer-sampling feature is
deliberately designed.

### Reviewer session timeout

Reviewer sessions follow the same time-bound allocation model as coder
sessions.

A reviewer allocation older than 1 hour is considered stale and must be
released automatically.

On reviewer session timeout:

- deactivate the active `va_allocations` row for reviewing
- deactivate active `va_reviewer_reviews` rows for the timed-out reviewer
- deactivate active `va_narrative_assessments` rows for the timed-out reviewer
- deactivate active `va_social_autopsy_analyses` rows for the timed-out
  reviewer
- return canonical workflow state to `reviewer_eligible`

Rationale: the reviewer final COD submission is the only terminal action for a
reviewer session. All intermediate saves are partial. A timed-out session that
did not reach final COD submission is treated as incomplete, and all
intermediate artifacts are discarded. A fresh reviewer session may then start
from `reviewer_eligible`.

Transition: `incomplete_reviewer_reset` → `reviewer_eligible`.

### Reviewer authority

Reviewer coding does not erase coder history.

Instead it must:

- preserve the coder decision as historical record
- create a distinct reviewer final-COD record
- make the reviewer submission auditable

Authoritative final COD precedence must be:

1. latest active reviewer final COD
2. otherwise latest active coder final COD

### Admin reset interaction

Admin may reset/reopen a submission at any time.

Admin does not author COD.

Admin reset returns the submission to the coder pool from any of:

- `coder_finalized`
- `reviewer_eligible`

Both states have no active session in progress, so the reset is safe.

For `reviewer_eligible` overrides: any intermediate reviewer session artifacts
from a prior timed-out session will have already been cleaned up by the
reviewer timeout release. No active reviewer COD exists at `reviewer_eligible`
(the reviewer never submitted a final COD). The recode episode is seeded from
the coder's authoritative final COD.

`reviewer_coding_in_progress` and `reviewer_finalized` are not eligible for
direct admin override — those cases must first go through the DM
accept/reject path if there is a data issue, or the reviewer session must
complete or time out.

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
- reviewer became eligible
- reviewer coding started
- reviewer final COD submitted
- stale allocation released

## Completion Rule

A case is considered locally complete when one of these business outcomes is
true:

- `coder_finalized`
- `finalized_upstream_changed` (pending resolution)
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

Reviewer activity may happen later, but it does affect final COD authority if a
reviewer final COD is later submitted.

## Related Documents

- [ODK Sync Policy](odk-sync-policy.md) — how sync interacts with workflow states
- [SmartVA Generation Policy](smartva-generation-policy.md) — when SmartVA runs
- [Final COD Authority Policy](final-cod-authority.md) — authoritative COD management
