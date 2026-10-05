---
title: Coding Workflow State Machine Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-05
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

A web intake case confirmed as a duplicate (`va_death_register.status =
duplicate`) is a case-level mark, not a workflow state: the submission's
workflow state is untouched, and confirming one whose coding is finalized needs
a supervisor holding a `data_manager` grant ([Web Intake Policy](web-intake.md),
"Duplicate on a submitted case"). See "Confirmed duplicate cases" below.

## Confirmed Duplicate Cases

Decisions 10 and 14 of `.tasks/2026-09-28-interviewer-worklist.md`.

- **One predicate.** Every reader of coding state excludes a submission whose
  web case is a confirmed duplicate through
  `app/services/duplicate_exclusion.py`: `not_confirmed_duplicate_condition`
  (ORM), `not_confirmed_duplicate_sql` (raw SQL, rendered from the same
  expression) or `is_confirmed_duplicate` (one submission named in a request).
  Readers are: random allocation, pick-and-choose list and pick, recode offer
  and start, admin override to recode, reviewer queue and reviewer start,
  coder and reviewer dashboard counts, the recode-window sweep to
  `reviewer_eligible`, SmartVA generation (skipped like a protected state
  unless forced), the data-manager grid and every export built on it,
  data-manager and area-dashboard counts over the analytics materialized
  views, the DM KPI endpoints and the daily KPI snapshot task, Site PI
  reporting, COD bucket reports and ICD search frequencies.
- **The mark is the case status, nothing else.** No workflow state is added,
  and `not_codeable_by_data_manager` is not reused. A pending (unconfirmed)
  duplicate flag excludes nothing.
- **Allocation revoked on confirmation.** An active coding allocation is
  released exactly as a timed-out one ([Coding Allocation Timeout
  Policy](coding-allocation-timeouts.md)): first pass back to
  `ready_for_coding`, recode back to `coder_finalized` with its authoritative
  COD, a reviewer session back to `reviewer_eligible`. Finished coding is
  never touched. Audited as `va_allocation_revoked_duplicate` /
  `reviewer_allocation_revoked_duplicate`.
- **Finalized duplicate.** Keeps its coding and workflow state and is excluded
  from every reporting count.
- **Undo.** A supervisor reopen of the case clears the mark; the submission
  returns to every reader in the workflow state it has (a revoked allocation
  stays released).
- **Not readers.** Workflow writers, sync and payload maintenance, MV
  definitions and refreshes, and single-submission paths behind an
  allocation keep working on a duplicate, so a reopen finds its data
  current. The list, with reasons, is `EXEMPT` in
  `tests/test_duplicate_exclusion_coverage.py`, which fails when a function
  reading coding state neither applies the predicate nor is listed.
- **Materialized views keep the rows.** Exclusion is applied at query time,
  so confirmation and reopen take effect without a refresh (cached dashboard
  responses may lag by their TTL).
- **Stored daily KPI rows are recounted.** Confirming or reopening queues
  `kpi_tasks.recompute_kpi_days_for_submission` after the commit. It recounts
  the `va_daily_kpi_aggregates` rows already stored for the submission's form
  site on the days its counts touched (created, last ODK update, and its
  coded, reviewer-finalized and reopened events); days with no stored row are
  live-filled by their readers. A past day keeps its end-of-day columns
  (pending, consent refused, not codeable, upstream changed), which record
  that day's backlog; today's row is recounted whole. Known ceiling:
  `total_submissions` is cumulative, so stored days between those recounted
  keep the old total until `flask kpi backfill` recomputes them.

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

## Coder Dashboard Output Metrics

The coder dashboard exposes authored-output metrics separately from the live
ready-pool metrics.

Current baseline:

- `Cumulative Forms Coded` must count active coder-authored final assessments
  on non-demo projects
- that count must continue to include cases after workflow advances from
  `coder_finalized` to `reviewer_eligible`
- `Marked Not Codeable` must be surfaced as a separate count based on active
  coder-authored Not Codeable reviews
- demo-training projects must not contribute to these authored-output counts
- these authored-output queries may be cached, but the cache must be busted
  whenever a coder submits a final COD or marks a case Not Codeable

## Step 1 Preservation

Current baseline:

- Step 1 COD is part of the traceable coding record for a submission
- submitting final COD must not deactivate or erase the coder's latest active
  Step 1 assessment for the same payload
- Step 1 may still be deactivated when a coder saves a newer Step 1 draft, when
  a stale coding session is reverted, or when data-manager upstream-change
  resolution explicitly invalidates the coding chain for recoding
- demo-created Step 1 COD is temporary and must be deactivated when the
  matching completed demo final COD expires
- reporting surfaces may show the preserved Step 1 assessment alongside final
  COD for the same submission

## Coding Access Gates

Coder workflow entry must enforce project-site coding gates for non-demo
projects.

Canonical non-demo coding gates:

- `coding_enabled = true`
- current date is on/after `coding_start_date` when a start date is set
- current date is on/before `coding_end_date` when an end date is set
- per project-site `daily_coder_limit` (keyed on the (project, site) pair) is not exceeded

Gate evaluation timezone:

- use UTC date for all coding gate checks

Role and bypass semantics:

- `coder` must satisfy all non-demo coding gates
- `coding_tester` may enter non-demo coding even when:
  - `coding_enabled = false`
  - current UTC date is before `coding_start_date`
  - current UTC date is after `coding_end_date`
  - per project-site `daily_coder_limit` (keyed on the (project, site) pair) has been reached
- project PI and site PI roles do not implicitly grant coder workflow entry;
  explicit coder or coding_tester access is still required to code

Retired-from-ODK gate:

- a submission retired from ODK (`va_sync_issue_code = missing_in_odk`) is not
  eligible for any new coding, recode, demo, or reviewer allocation, whatever
  its workflow state; existing active allocations run to their normal timeout.
  See [ODK Retired Submissions Policy](odk-retired-submissions.md).

## Demo Coding Mode

DigitVA supports demo coding through `vademo_start_coding` in two patterns:

- admin-started ad hoc demo sessions on ordinary projects
- project-declared demo/training projects

Demo coding uses the same case-viewing and coding forms as normal coding, but
it is not a permanent production completion path.

Current intended baseline:

- demo coding may save Step 1 COD, NQA, Social Autopsy Analysis, and final COD
  artifacts
- those demo artifacts must be visible immediately after save, including on the
  coder dashboard while they remain active
- project-declared demo/training projects are open, for both coding and
  reviewing, to admins and to every user who holds an active `coder`,
  `reviewer` or `coding_tester` grant somewhere; no grant on the demo
  project itself is needed (owner decisions 2026-10-02 and 2026-10-03)
- everyone else (interviewers, ASHA/ANM field staff, viewers, data managers
  without a coding role) never reaches a demo project or a coding screen
  through it, and demo projects never grant data management
- non-demo projects continue to require normal grant-based coding access
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
- `attachment_sync_pending`
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
the submission into `attachment_sync_pending`, then `smartva_pending` once
attachment syncing for the current payload finishes.

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
- `attachment_sync_pending` is now written in current runtime for newly synced
  and payload-changed consent-valid submissions
- `smartva_pending` is now written after attachment syncing finishes for the
  current payload

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

## Authority-Chain Preservation Rule

For protected upstream review decisions, coder and reviewer authoritative
artifacts move together.

Current baseline:

- reviewer-owned final COD is downstream of coder-owned final COD in the local
  authority chain
- reviewer supporting review artifacts follow the same preserve/deactivate
  decision as reviewer final COD when they exist
- if an upstream payload is accepted for recoding, the existing coder
  conclusion chain is invalidated and reviewer authoritative artifacts, if
  present, must also be deactivated
- if an upstream payload is promoted while keeping the current ICD decision,
  the existing coder conclusion chain is preserved and reviewer authoritative
  artifacts, if present, must also be preserved

Simple rule:

- coder rejected for recoding => reviewer rejected too, if reviewer artifacts
  exist
- coder retained => reviewer retained too, if reviewer artifacts exist

This preserves one coherent authoritative chain for the SID rather than
allowing coder and reviewer layers to diverge under the same upstream-review
decision.

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
                           | attachment_sync_     |
                           |        pending       |
                           +----------+-----------+
                                      |
                                      | attachment sync
                                      | completed for
                                      | current payload
                                      v
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
    - cleanup must also deactivate demo Step 1 COD, NQA, and Social Autopsy
      artifacts tied to the same completed demo coding outcome


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

### SmartVA on completion

A web or device interview is on no scheduled SmartVA path:
`sync_runtime_forms_from_site_mappings` returns only forms materialised from
ODK mappings, so `generate_all_pending` and the ODK sync never visit a
`form_source = 'web'` form (owner decision 2026-10-05, `digitva-533t`). The
service therefore queues SmartVA itself, in the background, so the result is
ready when a coder opens the case:

- after the transaction commits (never inside one that may roll back), once the
  case reaches `smartva_pending` through a web or device submit, a changed
  interviewer revision (including the server's own resubmission correction) or
  a supervisor's choice of another interview. It queues the Celery task
  `run_smartva_for_submission`, with trigger `web_intake_submit`,
  `interview_revision` or `supervisor_choice`.
- not queued for an unchanged revision, a superseded copy, a refused or
  incomplete interview (`consent_refused`), or an interview that has
  attachment references: that one waits in `attachment_sync_pending` for
  phase 2 and reaches SmartVA only after it.
- the task is idempotent: it skips a submission that already has an active
  result (success or recorded failure) for its current payload version, unless
  it was queued with `regenerate`. The existing helpers then move
  `smartva_pending` to `ready_for_coding` for a result and for a recorded
  failure alike.
- a Celery beat sweep every 30 seconds (`sweep_smartva_pending`) is the
  backstop: it runs SmartVA for every submission still in `smartva_pending`,
  batched per form (`generate_for_form`, trigger `smartva_sweep`), under a Redis
  lock so a long run is never overlapped, skipping sids that have a
  queued/running marker, confirmed duplicates and protected states. An empty
  sweep is one indexed query. It does not retry: a recorded failure moves the
  case to `ready_for_coding` (the coding page offers Run again), and a sid that
  stays pending after a sweep run is left alone for 10 minutes. So a broker
  failure after the commit delays SmartVA by at most one tick instead of
  leaving the case to the Run SmartVA button.

### SmartVA status on the coding page

The coding page (`va_coding.html`) has a SmartVA panel, status only (results
stay in the assessment steps, so masked Step 1 stays blind). The status is
derived, not stored: `queued` / `running` from a Redis key
`smartva-run:<va_sid>` (set when queued, replaced by `running` in the task,
cleared on every exit, TTL 30 minutes), else `done` / `failed` from the newest
active `va_smartva_results` row of the submission's *current* payload version,
else `not_requested`. A result of an earlier payload version (before a
revision) does not count. The panel offers Run SmartVA (`not_requested`), Run
again (`failed`) and Regenerate (`done`) through
`POST /api/v1/coding/submissions/<va_sid>/smartva`
([API v1](../current-state/api-v1.md)); a regeneration replaces the active
result only once the new run succeeds: a failed regeneration keeps the old
result active (the case keeps its SmartVA suggestion, the panel stays `done`)
and records the failure on the run record only. The request needs a coding-level
permission on the case (`Action.CODE`, `REVIEW` or `TRIAGE`; a view-only grant
or an out-of-scope coder gets 403), and the audit rows of a requested
regeneration name the requesting user and role
(`va_smartva_replaced_by_regeneration`, `va_smartva_regenerated`,
`va_smartva_regenerate_failed`). The queued marker is set when the sid is
queued inside the transaction (dropped on rollback), and the 30-second sweep
marks the sids it runs `running` for the length of their form's run, so the
panel shows it and a click does not double-queue. Not offered once the case is past coding (`SMARTVA_BLOCKED_WORKFLOW_STATES`)
or a confirmed duplicate, and not on the read-only views.

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
| Final COD | Current implementation keeps existing final assessment rows active and now stores explicit final-to-initial linkage via `va_final_assessments.source_initial_assessment_id` |
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
| Accept And Recode | Promote the new payload, transition to `smartva_pending`, rerun SmartVA for the new ODK data, and return to `ready_for_coding` only after generate/regenerate/failure-recording |
| Keep Current ICD Decision | Promote the new payload, preserve current COD/ICD artifacts, and restore the prior finalized workflow state |
| Admin override final COD | Transition from `coder_finalized` to `ready_for_coding` for recoding against the same payload; no SmartVA rerun required unless the payload has changed |

Policy baseline: data managers and admins may resolve
`finalized_upstream_changed` submissions.

Resolution UI baseline:

- the data-manager dashboard and the data-manager detail page may expose a
  `View Changes` action for pending `finalized_upstream_changed` submissions
- the upstream diff opens in a modal
- `Accept And Recode` and `Keep Current ICD Decision` belong inside that modal, not as standalone
  destructive buttons outside the modal
- `Accept And Recode` means the new ODK data becomes authoritative for recoding, old
  assigned ICD codes are cleared, and the form returns for recoding
- `Keep Current ICD Decision` means the new ODK data becomes the active stored
  payload while the current finalized ICD decision remains authoritative
- `Accept And Recode` also deactivates the old current coder NQA and Social
  Autopsy artifacts because the case will be coded again against new data
- `Keep Current ICD Decision` also rebinds the preserved active coder NQA,
  Social Autopsy, and SmartVA artifacts to the promoted payload
- these modal review actions are local DigitVA workflow decisions and
  do not post a rejection comment back to ODK Central

### Sent back or reopened for revision (web and device interviews)

`finalized_upstream_changed` also holds a web or device interview that a coder,
reviewer, supervisor, data manager or admin has opened for its interviewer's
revision ([Interview Revisions Policy](interview-revisions.md), rules 3 and
4). The same transition (`upstream_change_detected`) carries a different
transition reason, and the reason is what tells the two apart:

| Transition reason | Actor | From |
|---|---|---|
| `upstream_odk_data_changed` | system or admin (ODK sync) | `coder_finalized`, `reviewer_eligible`, `reviewer_finalized`, `finalized_upstream_changed` |
| `sent_back_for_revision` | the coder who finalised it, or a reviewer working on or eligible for it | `coder_finalized`, `reviewer_eligible`, `reviewer_finalized` (a reviewer's unfinished session is released first, so `reviewer_coding_in_progress` enters through `reviewer_eligible`) |
| `reopened_for_revision` | interview supervisor, data manager (supervision reach) or admin | `coder_finalized`, `reviewer_eligible`, `reviewer_finalized` |

Only these two reasons admit coder, reviewer, data-manager and
interview-supervisor actors; the ODK reason stays system and admin. Send-back
and reopen leave every coding artifact and the final COD active. The case is
open for revision while the latest workflow event that moved it into
`finalized_upstream_changed` carries one of those two reasons
(`get_open_revision_request`). An ODK upstream change on an ODK submission has
no such event: the interviewer's revision is refused (`revision_locked`) and the
data manager resolves it as above.

The interviewer's changed revision then restarts coding at once, with no
data-manager accept step: the accept block of "Accept And Recode" runs under a
system actor (`reopen_coding_after_revision`), with the transition
`upstream_change_accepted` (reason `interviewer_revision`, the only reason
that admits the system actor there), to `smartva_pending`. The earlier COD is
deactivated, never deleted. An unchanged revision does nothing and the case
stays open. A data manager's `Keep Current ICD Decision` (reject) on such a
case cancels it: the case returns to the state it was sent back from, its
coding untouched (reason `data_manager_cancelled_revision_request`); `Accept
And Recode` has no upstream payload to accept and is refused.

### Authorization

| Operation | Coder | Data Manager | Admin |
|---|---|---|---|
| View upstream-changed submissions | No | Yes (scoped) | Yes |
| Accept And Recode | No | Yes (scoped) | Yes |
| Keep Current ICD Decision | No | Yes (scoped) | Yes |

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
