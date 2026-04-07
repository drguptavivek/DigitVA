---
title: Workflow And Permissions
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-07
---

# Workflow And Permissions

## Summary

After sync, the application runs a role-based workflow over `va_submissions`.

Primary roles:

- coder
- data manager
- reviewer
- site PI
- admin

Current admin scope rule:

- `admin` is global-only in the implemented grant model
- project- or site-scoped admin grants are not supported
- admin-only workflow actions such as override-to-recode therefore rely on
  global admin membership, not submission scope checks

Current demo/training access rule:

- a project may be marked as a training pool using
  `va_project_master.demo_training_enabled`
- active forms in those projects are treated as coder-accessible without any
  project-specific coder grant
- in practice, any active authenticated user can enter the coder flow for
  those demo/training project forms
- non-demo projects still require ordinary coder grants
- the coder dashboard now exposes a dedicated `DEMO-CODING` shortcut when at
  least one demo/training project is available to the current user
- that shortcut preselects the first demo/training project on the page and
  shows an inline warning that:
  - completed demo/training codes persist for 10 minutes by default
  - incomplete demo/training allocations are revoked after 15 minutes

The current workflow is built around form-based permissions and per-submission
allocation.

Current payload-lineage rule for coder-owned supporting artifacts:

- coder NQA and Social Autopsy are now payload-version aware
- the current artifact for a coder is the active row whose
  `payload_version_id` matches `va_submissions.active_payload_version_id`
- `Accept And Recode` deactivates those current artifacts because coding will
  restart against new data
- `Keep Current ICD Decision` preserves them by rebinding them to the promoted
  payload

Current authority-chain rule for finalized artifacts:

- reviewer-owned final COD is treated as downstream of coder-owned final COD
- if `Accept And Recode` is chosen for a protected upstream change, both coder
  and reviewer final COD artifacts are deactivated as current authoritative
  results
- if `Keep Current ICD Decision` is chosen, both coder and reviewer final COD
  artifacts are preserved as current authoritative results, if reviewer
  artifacts exist for that SID

Current payload-lineage rule for reviewer supporting artifacts:

- reviewer review/NQA rows are now payload-version aware
- the current reviewer review is the active row whose `payload_version_id`
  matches `va_submissions.active_payload_version_id`
- `Accept And Recode` deactivates reviewer review rows because the reviewer
  conclusion chain is discarded with the coder chain
- `Keep Current ICD Decision` preserves reviewer review rows by rebinding them
  to the promoted payload

An additive canonical workflow-state table now exists:

- `va_submission_workflow`
- `va_submission_workflow_events`

This table stores one local business-state row per submission, but the
application is still in migration. Legacy workflow tables still drive
completion history, recode behavior, and some reporting paths.

Current cutover status:

- coder random allocation reads `va_submission_workflow`
- admin demo allocation reads `va_submission_workflow`
- coder dashboard available-form count reads `va_submission_workflow`
- coder dashboard completed-history count and status labels now read
  `va_submission_workflow`
- project-level `coding_intake_mode` is now stored on `va_project_master`
  with `random_form_allocation` as the default
- coder dashboard now splits eligible coding intake by project mode:
  - `random_form_allocation` projects use the existing start button
  - `pick_and_choose` projects expose a browse-and-start list
- data-manager dashboard now exists as a scope-based browse/view workflow
- data-manager Not Codeable writes canonical workflow state
  `not_codeable_by_data_manager`
- final COD display now prefers explicit authority resolution through
  `va_final_cod_authority`
- recode now starts a separate non-destructive episode in `va_coding_episodes`
  instead of immediately discarding the current finalized coder outcome
- workflow state ownership is being consolidated under `app/services/workflow/`
- runtime state transitions now flow through `app/services/workflow/transitions.py`
  using explicit actor types:
  - `vasystem`
  - `vaadmin`
  - `vacoder`
  - `data_manager`
- canonical state persistence is handled in
  `app/services/workflow/state_store.py`
- canonical workflow events are now written to
  `va_submission_workflow_events`
- transition execution now takes a row lock on the submission workflow record
  before validating and writing state, reducing concurrent transition races

## Current State vs Desired State

Current implemented workflow states written by the runtime are a subset of the
full policy target.

Implemented in current runtime:

- `consent_refused`
- `screening_pending`
- `attachment_sync_pending`
- `smartva_pending`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved` (legacy compatibility only; current runtime no longer
  creates new rows in this state)
- `coder_step1_saved`
- `coder_finalized`
- `reviewer_eligible`
- `reviewer_coding_in_progress`
- `reviewer_finalized`
- `finalized_upstream_changed`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

Desired target states are documented in
[Coding Workflow State Machine Policy](../policy/coding-workflow-state-machine.md).
The planned gap-closure sequence is documented in
[Plan: Finalized Upstream Change Gap Closure](../planning/finalized-upstream-change-gap-plan.md).

Current rename note:

- runtime/data now use `finalized_upstream_changed`
- legacy migrated key: `revoked_va_data_changed`
- UI target label remains `Finalized - ODK Data Changed`

## Main Workflow Sequence

1. ODK sync writes or updates `va_submissions`.
2. The workflow layer routes new or payload-changed submissions to:
   - `consent_refused`, or
   - `attachment_sync_pending`
3. Attachment completion for the current payload moves the submission to
   `smartva_pending`.
4. SmartVA completion for the current payload moves the submission to
   `ready_for_coding`.
5. Eligible submissions become visible in coding dashboards only after they are
   `ready_for_coding`.
6. A user starts coding or review, which creates an allocation.
7. The user works through the category UI and submits outcomes.
8. The allocation is released when work is completed or a terminal workflow
   decision is recorded.

## Coder Workflow

Project-level intake setting:

- `va_project_master.coding_intake_mode`
- supported values:
  - `random_form_allocation`
  - `pick_and_choose`

Project-level screening note:

- `screening_pending` is an optional project-configured gate
- screening-enabled projects may route submissions through
  `screening_pending -> smartva_pending` or
  `screening_pending -> not_codeable_by_data_manager`
- projects without screening bypass that state and route directly to
  `smartva_pending`

Current implementation status:

- the setting is now editable in the admin Projects panel
- `random_form_allocation` projects still use the existing start-coding flow
- `pick_and_choose` projects now render an eligible-submission browse table on
  the coder dashboard
- pick-and-choose start uses the dedicated `vapickcoding` action and still
  creates a normal coding allocation plus `coding_in_progress` workflow state

Coder dashboard behavior:

- the coder sees submissions only if:
  - the submission's `va_form_id` is in the coder's permitted forms
  - the form's `(project_id, site_id)` pair is currently active in
    `va_project_sites`
  - the submission language is in the coder's allowed languages
  - the submission's canonical workflow state is eligible for coding
- completed-history rows and the cumulative coded count now use canonical
  workflow states:
  - `coder_finalized`
  - `not_codeable_by_coder`
- the dashboard still reads underlying final-assessment / coder-review rows for
  display timestamps and actor attribution during the migration period

Starting coding:

- the app creates a `va_allocations` row for the chosen submission
- the app also records `coding_in_progress` in `va_submission_workflow`
- stale coding allocations older than one hour are released automatically
- the release path deactivates only the stale coding allocation
- any saved `va_initial_assessments` row is preserved so the coder can resume
  final COD later
- admin demo coding also creates a normal coding allocation, but demo-created
  NQA, Social Autopsy, and final COD artifacts now carry a `demo_expires_at`
  timestamp
- for ordinary projects started through admin demo mode, the expiry window is
  6 hours
- for `demo_training_enabled` projects, the expiry window comes from
  `va_project_master.demo_retention_minutes` and defaults to 10 minutes

Entry variants:

- `vastartcoding` picks from only the coder-accessible projects configured for
  `random_form_allocation`
- `vapickcoding` is available only for ready submissions in coder-accessible
  projects configured for `pick_and_choose`
- a submission in a `demo_training_enabled` project automatically uses
  `vademo_start_coding` even when entered from the normal coder start/pick
  flow, so demo retention and cleanup apply without a separate admin-only demo
  launch

Coding steps:

- initial assessment creates a `va_initial_assessments` row
- initial assessment also records `coder_step1_saved` in `va_submission_workflow`
- final coding creates a `va_final_assessments` row
- final coding stamps that row with the submission's current
  `active_payload_version_id`
- final coding also records `coder_finalized` in `va_submission_workflow`
- not-codeable path creates a `va_coder_review` row
- coder Not Codeable also records `not_codeable_by_coder` in
  `va_submission_workflow`
- when a coder marks a case Not Codeable, DigitVA saves the local outcome first
  and then separately attempts to push `hasIssues` review state to ODK Central

Completion behavior:

- final coding or not-codeable submission deactivates the active coding allocation
- demo final coding now keeps the saved NQA, Social Autopsy, and final COD rows
  active immediately after submission so they remain visible in the dashboard
  during the demo-retention window
- reviewer final coding creates a `va_reviewer_final_assessments` row stamped
  with the submission's current `active_payload_version_id`
- final COD authority resolution now ignores stale coder/reviewer final rows
  from older payload versions

Timeout cleanup:

- the app still performs a stale-allocation release check when a coder starts
  normal coding
- a Celery beat task also runs every hour to release stale coding allocations
- normal coding allocations expire after 1 hour
- demo/training coding allocations expire after 15 minutes
- timeout release writes a `va_submissions_auditlog` row with
  `va_allocation_released_due_to_timeout`
- timeout release now reverts unfinished Step 1 COD drafts by deactivating the
  timed-out coder's active `va_initial_assessments` row
- first-pass timeout reversion also deactivates the timed-out coder's NQA and
  Social Autopsy analysis rows so the submission returns to
  `ready_for_coding`
- recode timeout reversion preserves the authoritative final COD plus recode NQA
  and Social Autopsy analysis rows, abandons the active recode episode, and
  returns canonical workflow state to `coder_finalized`
- recode start/finalization now require an active recode episode as a workflow
  precondition, not just route/service branching
- the same hourly maintenance task now also deactivates expired demo-created
  NQA, Social Autopsy, and final COD rows whose `demo_expires_at` timestamp is
  older than the current time
- demo/training project saved artifacts use the project retention window and
  default to 10 minutes
- that hourly maintenance path now moves
  `coder_finalized -> reviewer_eligible` once the authoritative final COD is
  older than the 24-hour recode window and there is no active recode episode
- when demo-retention cleanup deactivates an authoritative demo final COD, it
  also clears or repoints `va_final_cod_authority` and restores canonical
  workflow state based on the remaining active records

Canonical state values currently written in the runtime path include:

- `consent_refused`
- `ready_for_coding`
- `coding_in_progress`
- `partial_coding_saved`
- `coder_step1_saved`
- `coder_finalized`
- `reviewer_eligible`
- `finalized_upstream_changed`
- `not_codeable_by_coder`
- `not_codeable_by_data_manager`

The `closed` state still exists as a defined legacy compatibility constant for
historical rows and protection logic, but current runtime does not write it in
normal case handling. Current runtime treats `reviewer_eligible` as the
post-24-hour resting state for coder-finalized submissions.

`attachment_sync_pending` is now written for newly synced and payload-changed
submissions while attachment batching finishes for the current payload.

`smartva_pending` is now written only after attachment syncing completes for
the current payload and before SmartVA completes.

Current remaining reader/reporting gap:

- analytics MV and Site PI reporting now honor reviewer authority
- some older coder-participation detail slices still read coder-owned tables
  directly because they are measuring coder activity, not authoritative final
  COD

## Data Manager Workflow

Scope model:

- data-manager access is granted at:
  - `project`
  - `project_site`

Current runtime behavior:

- a data manager sees all submissions in granted scope, regardless of coder
  allocation
- data-manager view uses the same category rendering shell in read-only mode
- category visibility currently follows the site-PI visibility configuration
- the left navigation adds a synthetic final panel:
  - `vadmtriage`
- the dashboard now exposes:
  - ODK review state mirrored from ODK Central
  - local sync issue status
  - scoped form sync
  - scoped single-submission refresh

Data-manager triage:

- the `Data Triage` panel can mark a submission Not Codeable only while the
  canonical workflow state is:
  - `screening_pending`
  - `smartva_pending`
  - `ready_for_coding`
  - `not_codeable_by_data_manager`
- a successful triage write creates or updates `va_data_manager_review`
- the canonical workflow state is updated to `not_codeable_by_data_manager`
- coder availability excludes those submissions automatically because coder pool
  selection now requires `ready_for_coding`
- the POST path now also enforces an explicit `current_user.is_data_manager()`
  check before it records the transition

Data-manager sync controls:

- a data manager can trigger a force-resync for any form in granted scope
- a data manager can trigger a single-submission refresh for any submission in
  granted scope
- the single-submission refresh updates local submission data, attachments, and
  SmartVA result for that submission

Audit trail:

- canonical workflow state changes are recorded in
  `va_submission_workflow_events`
- `va_submissions_auditlog` is now the non-workflow operational audit trail
- current milestone examples include:
  - `form allocated to coder`
  - `social autopsy analysis saved` / `updated`
  - `narrative quality assessment saved` / `updated`
  - `initial cod submitted`
  - `final cod submitted`
- `error reported by coder`
- `odk review state set to hasIssues`
- `odk review state update failed`

Recode:

- only coder-finalized submissions are currently eligible for recode
- recode is now additive:
  - starting recode creates or reuses an active `va_coding_episodes` row
  - the current authoritative final COD remains in force during the recode
    window
  - successful replacement final COD supersedes the prior authoritative final
    COD and completes the recode episode
- the recode start window is currently twenty-four hours from the authoritative
  final COD timestamp
- stale allocation timeout abandons the active recode episode without deleting
  the previously authoritative final COD
- sync updates that invalidate an existing finalized COD also abandon any active
  recode episode and clear final-COD authority for that submission

Final COD authority:

- the coding UI now resolves "current final COD" through
  `va_final_cod_authority` first
- fallback to the newest active `va_final_assessments` row still exists for
  backward compatibility during migration
- a replacement final COD submission now:
  - deactivates the superseded active final-assessment rows
  - writes audit entries for supersession
  - updates `va_final_cod_authority`
  - completes the active recode episode if one exists

### Coding Screen Left Navigation

The coder/reviewer left navigation is now built dynamically from:

- form-type category config
- live submission data visibility
- role-aware category rendering rules

The stored `va_submissions.va_category_list` remains a legacy derived field, but
it no longer controls the visible category flow in coding.

## Reviewer Workflow

Reviewer dashboard behavior:

- reviewer visibility is filtered by permitted forms and allowed narration languages

Starting review:

- the app creates a reviewing allocation (`VaAllocation.reviewing`)
- state transitions to `reviewer_coding_in_progress`

Reviewer NQA (supporting artifact, optional):

- the reviewer may submit a `va_reviewer_review` (NQA) record during their
  session — this is a partial save only
- NQA save does NOT release the reviewing allocation and does NOT advance
  workflow state; it is a supporting artifact equivalent to Social Autopsy
  Analysis for coders

Reviewer final COD (terminal action):

- the reviewer submits a final COD via `submit_reviewer_final_cod()`
  (`app/services/reviewer_coding_service.py`)
- this releases the reviewing allocation and transitions to `reviewer_finalized`
- `va_final_cod_authority` is updated to point to the reviewer's final assessment

Reviewer session timeout:

- stale `reviewer_coding_in_progress` allocations are released by
  `release_stale_reviewer_allocations()` on a 1-hour schedule (and
  opportunistically at `start_reviewer_coding()` entry)
- on timeout: all intermediate artifacts (`va_reviewer_review`,
  `va_narrative_assessments`, `va_social_autopsy_analyses` for that user) are
  deactivated; state reverts to `reviewer_eligible`
- policy: `docs/policy/coding-allocation-timeouts.md`

Current reviewer model note:

- current runtime now marks post-24-hour coder-finalized submissions as
  `reviewer_eligible`
- runtime now also supports reviewer secondary-coding workflow states:
  - `reviewer_coding_in_progress`
  - `reviewer_finalized`
- reviewer JSON API exists for reviewer allocation and reviewer final-COD
  submission (`app/routes/api/reviewing.py`)
- the older `va_reviewer_review` NQA flow is a supporting artifact; it does
  not control workflow state or allocation lifecycle
- reviewer secondary coding opens only after the coder's 24-hour recode window
  closes
- admin may reset/reopen a case at any time and return it to the coder pool
  (from `coder_finalized` or `reviewer_eligible`; NOT from
  `reviewer_coding_in_progress` or `reviewer_finalized`)
- reviewer final COD authority now resolves ahead of coder final COD in the
  authority service and main submission display path
- additive reviewer final-COD storage exists in `va_reviewer_final_assessments`
- `va_final_cod_authority` has reviewer-pointer support; reviewer submission
  updates that authority row

Workflow event history:

- every workflow transition is logged to `va_submission_workflow_events`
- event history is exposed via:
  - `GET /api/v1/workflow/events/<va_sid>` — JSON endpoint
  - `GET /vaform/<va_sid>/workflow_history` — HTMX HTML partial

## Site PI Behavior

Site PI currently has a reporting-oriented dashboard rather than a full
operational workflow.

Current site PI capabilities:

- site-level KPI viewing
- authoritative-coded totals that now include reviewer-finalized cases
- workflow outcome counts, including:
  - `reviewer_eligible`
  - `reviewer_finalized`
  - `finalized_upstream_changed`
- workflow repair-cycle totals sourced from canonical workflow events,
  including:
  - admin resets
  - upstream-change detection and acceptance
  - recode starts and finalizations
  - reviewer coding starts and finalizations
- per-submission workflow-cycle rows showing current state, authority source,
  and event counts
- coder participation reporting, which still intentionally uses coder-owned
  tables because it measures coder activity rather than final authority

Implementation note:

- Site PI dashboard reporting now resolves through
  `app/services/sitepi_reporting_service.py`
- that service is site-scoped through `va_forms.site_id` and no longer relies
  on the earlier mixed site/form assumptions

## Permissions Model

### Current source of truth

Permissions are stored on the user record in:

- `va_users.permission`

This is a JSONB structure.

An additive grants table also now exists in schema:

- `va_project_master`
- `va_site_master`
- `va_project_sites`
- `va_user_access_grants`

Important:

- coder authorization in the current dev environment now resolves from `va_user_access_grants`
- site PI authorization in the current dev environment now resolves from `va_user_access_grants`
- reviewer authorization in the current dev environment now resolves from `va_user_access_grants`

### Current permission helpers

The user model provides helpers such as:

- `is_coder()`
- `is_reviewer()`
- `is_site_pi()`
- `get_coder_va_forms()`
- `get_reviewer_va_forms()`
- `has_va_form_access()`

### Current effective model

Permissions are currently mixed during transition.

For example:

- coder access is derived from grant scope, then resolved back to form access through `va_project_sites` and `va_forms`
- site PI access is derived from grant scope, then resolved back to form access through `va_project_sites` and `va_forms`
- reviewer access is derived from grant scope, then resolved back to form access through `va_project_sites` and `va_forms`

### Language as second filter

Visibility is also filtered by:

- `current_user.vacode_language`

So a coder may have form access but still not see a submission if the narration language does not match profile settings.

## Route-Level Validation

The main route guard is:

- [`va_validate_permissions`](../../app/decorators/va_validate_permissions.py)

It validates:

- dashboard access by role
- coding and review action URLs
- submission access based on current user's form permissions and workflow state

## Admin Runtime Access

An additive admin JSON API now exists under:

- `/admin/api/...`

Current baseline:

- `admin` may manage all admin API resources
- `project_pi` may manage project-site mappings and non-global access grants only inside explicitly granted projects
- `data_manager` may create users and manage coder/data_manager grants within their own grant scope via `/data-management/users`
- `admin` may also use the data-manager user management interface with full scope access
- browser-originated mutating admin API requests require the `X-CSRFToken` header

## Important Current-State Limitation

The permission model is built around synthetic app form identity.

This matches the current single-project-first design, but it is not a good long-term fit for:

- reusable sites
- reusable form types
- deployment-based ODK mappings
- project-scoped or site-scoped access models
