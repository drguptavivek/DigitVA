---
title: Workflow And Permissions
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-28
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

Current coding tester gate rule:

- `coding_tester` is a grant role that can enter non-demo coding while
  bypassing project-site gates:
  - `coding_enabled`
  - `coding_start_date`
  - `coding_end_date`
  - `daily_coder_limit`
- coding gate date checks use UTC date boundaries

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
- coder dashboard authored-output KPIs now read the coder's active authored
  final assessments and active authored Not Codeable reviews, excluding
  demo-training projects
- coder dashboard "Cumulative Forms Coded" includes coder-authored active
  final assessments even after workflow advances from `coder_finalized` to
  `reviewer_eligible`
- coder dashboard shows a separate authored `not_codeable_by_coder` count
- coder dashboard authored-output stats/history are cached and busted on coder
  final submission and coder Not Codeable submission
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

ICD coding allowability:

- ICD coding search filters selectable ICD10-2019-2 rows by the submission's
  classified age group and sex
- initial, final, and reviewer final COD save paths enforce the same
  ICD10-2019-2 coding policy server-side before creating new COD rows
- policy-disallowed posted values are rejected even if they came from stale UI
  options or manually edited requests

Completion behavior:

- final coding or not-codeable submission deactivates the active coding allocation
- demo final coding now keeps the saved NQA, Social Autopsy, and final COD rows
  active immediately after submission so they remain visible in the dashboard
  during the demo-retention window
- completed demo Step 1 COD is temporary; when its matching demo final COD
  expires, cleanup deactivates the same coder's active Step 1 row
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
- demo-retention cleanup deactivates the expired demo coder's active
  `va_initial_assessments` row before restoring workflow state, so completed
  demo/training submissions can return to `ready_for_coding`
- demo-retention cleanup no longer emits a demo reset for submissions that
  still have an active coding allocation; in that case it prunes the expired
  demo artifacts but keeps the live coding or recode session state intact

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

### Retired submissions and coding pools

A submission whose `va_sync_issue_code` is `missing_in_odk` is retired from ODK
(see [ODK Retired Submissions Policy](../policy/odk-retired-submissions.md)).
Every pool that can create a new allocation applies the shared predicate
`submission_is_in_odk()`
([`app/services/odk_retirement_service.py`](../../app/services/odk_retirement_service.py)),
never a locally re-derived comparison:

- coder random pool, pick-and-choose list, and the ready counts behind
  `/api/v1/coding/stats`, `/api/v1/coding/available` and the `/coding/`
  dashboard (`_available_submission_filters()` in
  [`app/services/coder_workflow_service.py`](../../app/services/coder_workflow_service.py))
- the demo/training pool (`start_demo_allocation()`)
- the recode offer list (`get_coder_recodeable_sids()`)
- the reviewer dashboard pool, which still shows a retired submission whose
  review is already done or still in session

Entry points refuse a direct URL with HTTP 409 and the policy message
(`RETIRED_MESSAGE`): `POST /coding/pick/<sid>`, the `vapickcoding` and
`vastartreviewing` validators, `allocate_pick_form()`,
`start_recode_allocation()` and `start_reviewer_coding()`.

Existing allocations are unaffected: a submission retired mid-session keeps its
allocation until the normal timeout, so `varesumecoding` and
`varesumereviewing` still work, and completed coding is untouched.

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

Demo reviewing (`demo_training_enabled` projects):

- a demo coder final COD moves the case `coder_finalized -> reviewer_eligible`
  at once (`demo_reviewer_eligible_immediately`); admin-started demo sessions
  on ordinary projects keep the 24-hour recode window
- demo project forms join every active user's reviewer scope, as they join
  coder scope, so any user may review demo cases; non-demo forms stay grant-only
- when the coder's demo final COD expires, demo-retention cleanup also
  deactivates the case's reviewer final/initial COD, reviewer review, NQA,
  Social Autopsy and reviewing allocation (audited), clears the reviewer
  authority pointer, and `reset_demo_state` (now allowed from the three
  reviewer states) returns the case to `ready_for_coding`

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
- unit-scoped (`org_unit`) grants reach the forms of their unit's project, and
  for projects with an active organization tree the submissions of those forms
  are then narrowed to the coder's own unit subtree, honouring the project's
  coding scope level and above-scope mode
  (`app/services/org_grant_service.py::codeable_unit_ids`)
- the narrowing is applied in the shared availability filter
  (`coder_workflow_service._org_unit_scope_filter`, used by the pick list,
  random allocation and the dashboard counts) **and** per submission when one
  is opened or allocated (`submission_within_org_scope`, called once for every
  coding and reviewing action in `va_validate_permissions`)
- projects with no organization tree are unaffected: the filter excludes
  nothing for them, so the form-and-site model is unchanged
- an unrouted submission of a tree project is codeable by nobody until a data
  manager routes it (policy: `docs/policy/organization-model.md`)

### Closed projects resolve no grant

Every resolver that turns a grant into access requires the grant's project to
have `project_status = active`, through the shared predicate
`app/services/org_grant_service.py::active_project_condition`. A project- ,
site- or unit-scoped grant on a closed project resolves to nothing for every
non-admin role, in both mechanisms (`org_grant_service` and the
`VaUsers._get_granted_*` helpers the data-management path uses). The grant
rows are untouched, so reopening the project restores access unchanged.
Admins hold a `global` grant and are not grant-resolved against a project, so
admin access is unaffected. Policy:
`docs/policy/access-control-model.md`, "Closed Projects".

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

## Login Flow (two-step, digitva-sn1.1)

Baseline: `docs/policy/authentication-factors.md`. As of 2026-09-28, `/vaauth/valogin`
is step 1 only:

1. **Email step** (`va_auth.va_login`, GET/POST). The browser solves a local
   proof-of-work CAPTCHA in a Web Worker
   (`app/static/js/pow_captcha.js` + `pow_captcha_worker.js`, challenge from
   `va_auth.va_login_captcha_challenge`, verified server-side by
   `app/services/pow_captcha_service.py`). On success the server stores a
   pre-authentication state (`session["preauth"]`: email, issued-at, safe
   `next`) and redirects to step 2. This step never looks up `VaUsers` and
   responds identically for a known or unknown email.
2. **Password step** (`va_auth.va_login_password`, GET/POST, `/vaauth/valogin/password`).
   Requires a live, unexpired (5-minute) pre-auth state or redirects back to
   step 1. Runs the existing checks unchanged (password, `user_status`,
   email-verified, maintenance cutoff, safe `next`) and completes sign-in.
   The same page shows a "Use a passkey" button above the password form for
   every email, known or not (`app/static/js/webauthn_login.js`); the
   button hides itself when `window.PublicKeyCredential` is missing, and a
   cancelled or failed ceremony shows a neutral message and leaves the
   password form usable.
3. **Passkey path** (`va_auth.va_login_passkey_options` /
   `va_auth.va_login_passkey_verify`, POST-only JSON, both under
   `/vaauth/valogin/passkey/`). Also requires a live pre-auth state.
   `..._options` returns discoverable-credential authentication options
   (no `allowCredentials`, nothing derived from the pre-auth email) built
   by `app/services/webauthn_service.py`, so the response is byte-identical
   for a known or unknown email. `..._verify` looks the asserted credential
   up by its ID, refuses unless it belongs to the pre-auth email's own
   account, applies the signature-counter policy itself (counter 0/0 is
   fine; a non-zero stored counter the new value fails to exceed is refused
   and logged as `counter_regression`), atomically bumps the stored
   `sign_count`, and completes sign-in through the same shared
   `_complete_login()` helper the password path uses.
4. **Session versioning.** `VaUsers.auth_session_version` (migration
   `c1d5e9a2f7b4`) lets a password reset, and later a factor reset or the
   break-glass CLI, invalidate every existing session and remember cookie:
   `VaUsers.get_id()` returns `"<uuid>:<version>"` once the version is
   non-zero, bare `"<uuid>"` at version 0 so pre-existing sessions keep
   working; the `login.user_loader` and every other place that reads
   `session["_user_id"]` accept both forms.
5. **Reauthentication window.** `_complete_login()` stamps
   `session["auth_verified_at"]` on every successful sign-in (password or
   passkey). Registering, renaming or revoking a passkey in Profile
   (`/api/v1/profile/passkeys*`) needs that timestamp to be under 10 minutes
   old, else the route returns `401 {"error": "reauth_required"}` and the
   page prompts for the password again (`POST /api/v1/profile/reauth`).
6. **Post-login nudge.** A password sign-in by a user with no registered
   passkey sets `session["passkey_nudge"]`; `va_base.html` then renders a
   dismissible banner on the next page linking to the Profile passkey
   section. Dismissing it (`POST /api/v1/profile/dismiss-passkey-nudge`)
   clears the session flag, so it does not reappear for the rest of the
   session. A passkey sign-in never sets the flag.
7. **Second-factor step** (`va_auth.va_login_second_factor`, GET/POST,
   `/vaauth/valogin/second-factor`). Only reached when
   `app/services/totp_service.py:needs_second_factor()` says so: the user
   holds a confirmed TOTP enrolment (any role), or is privileged (active
   `admin`/`data_manager` grant) and holds any factor (passkey or confirmed
   TOTP) — docs/policy/authentication-factors.md section 3. The password
   step, on a correct password for such a user, stores
   `second_factor_user_id`/`second_factor_failures`/`remember` on the same
   pre-auth state instead of calling `_complete_login()`, and redirects
   here; the page is unreachable without that verified-password marker on
   the live pre-auth state. Accepts a current TOTP code
   (`totp_service.verify()`, +/-1 step drift, atomic replay protection on
   `auth_totp.last_used_step`) or an unused recovery code
   (`totp_service.verify_recovery_code()`, atomic single-use consumption on
   `auth_recovery_codes.used_at`; logs `recovery_code_used` with the
   remaining count). A privileged user with only passkeys sees the
   recovery-code field plus a "Use a passkey instead" link back to the
   password page. Five failed attempts clear the pre-auth state, log
   `second_factor_lockout`, and redirect to the email step.

**TOTP and recovery codes** (`app/services/totp_service.py`). TOTP secrets
are AES-256-GCM-encrypted at rest under a key derived (HKDF-SHA256) from
`AUTH_FACTOR_ENCRYPTION_KEY`, bound to the owning user as associated data
(`config.py`; production requires that key set to a valid 32-byte
urlsafe-base64 value — see `create_app`; development/test derive one from
`SECRET_KEY`). Values written before this scheme (legacy Fernet) still
decrypt and are re-encrypted on next successful use. Recovery
codes are stored only as HMAC-SHA256 hashes keyed off the same secret under
a distinct label, shown to the caller exactly once at generation time.
Recovery codes are issued automatically the moment a user enrols their
*first* factor — at TOTP confirmation if they hold no passkey yet
(`POST /api/v1/profile/totp/confirm`), or at first passkey registration if
they hold no confirmed TOTP and no recovery-code set yet
(`POST /api/v1/profile/passkeys`) — and returned once in that response
body. Profile API (`app/routes/api/profile.py`, all reauth-gated like the
passkey routes): `GET/POST/DELETE /api/v1/profile/totp` (status, start
enrolment — returns the secret, provisioning URI and an inline SVG QR code
from `segno` — and removal) plus `POST /api/v1/profile/totp/confirm`, and
`GET /api/v1/profile/recovery-codes` / `POST .../regenerate` (regenerating
voids the old set). **Last-factor removal guard**: once
`AUTH_FACTOR_ENFORCE_FROM` is set and its date has passed
(`totp_service.enforcement_active()`; unset/future means the guard is off),
a privileged user cannot remove their last factor — checked in both the
TOTP-removal route and the existing passkey-revoke route, `409` on
violation.

**8. Enrolment enforcement, admin reset and the break-glass CLI**
(docs/policy/authentication-factors.md section 6, 8). Before
`AUTH_FACTOR_ENFORCE_FROM`, a privileged user (admin or `data_manager`) with
no factor sees a banner naming the deadline on every page
(`app/__init__.py:_factor_enrollment_banner_context`, rendered in
`va_base.html`); unset means no banner at all. On or after that date,
`app/__init__.py`'s `enforce_factor_setup` before-request hook redirects
every request from such a user to `profile.view#passkeys-card`, except the
Profile page itself, the whole `api_v1.profile_api` blueprint, `va_auth.*`
(login/auth/logout/recovery), static files and the health check; an API/admin
path gets `403 {"error": "factor_setup_required"}` instead. No lock-out — a
password sign-in still works. The "has a factor" answer is cached in
`session["factor_setup_needed"]` and popped by the four routes that change a
user's factor set (`register_passkey`, `revoke_passkey`, `totp_confirm`,
`totp_remove`), so it costs no query once satisfied.

**Admin reset** (`POST /admin/api/users/<id>/reset-factors`, `role_required("admin")`,
refused for yourself, requires a non-empty `reason`) and the **break-glass
CLI** (`flask auth reset-factors EMAIL --reason=...`) both call
`totp_service.reset_factors()`: delete the user's passkeys/TOTP/recovery
codes, `bump_session_version()` (ends every session and remember cookie),
and record a `factor_reset` security event (`actor_user_id` set for the
admin path, `NULL` for the CLI; `detail={"reason": ..., "via": "admin"|"cli"}`).
The admin path emails the user with no link (`send_factor_reset_email`,
async via Celery); the CLI additionally generates a `factor_reset` token
(`token_service`, 1 hour, fingerprinted on the password hash *and*
`auth_session_version` together, so either a password change or any other
reset invalidates it) and emails a single-use magic link **synchronously**
(`send_factor_reset_link_email` — the CLI's contract is "print the link only
if sending failed", which a queued Celery task cannot report). The link lands
on `va_auth.factor_reset` (public by design, `PUBLIC_BY_DESIGN` in
`tests/test_route_auth_coverage.py`): the existing `ResetPasswordForm`/
password-breach-check flow, then `email_verified = True`,
`bump_session_version()`, `_complete_login()`, and
`session["factor_setup_forced"] = True` so the redirect guard holds a
privileged user on the factor-setup page even if `AUTH_FACTOR_ENFORCE_FROM`
is unset, until they enrol.

Schema: `auth_webauthn_credentials`, `auth_totp`, `auth_recovery_codes`
(all in use), `auth_security_events` (`passkey_registered`,
`passkey_renamed`, `passkey_revoked`, `counter_regression`,
`totp_enrolled`, `totp_removed`, `recovery_codes_generated`,
`recovery_code_used`, `second_factor_lockout`, `factor_reset`) plus
`va_users.auth_session_version`.

WebAuthn RP ID/origin: `config.py`'s `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN`
default to the host / scheme+host of `MAIL_BASE_URL` (via the same
`_parse_public_url` helper `trusted_hosts_for` uses), overridable by
environment variable for development; with no `MAIL_BASE_URL` at all they
fall back to `localhost` / `http://localhost:8051`, which WebAuthn allows
over plain HTTP.

## Admin Runtime Access

An additive admin JSON API now exists under:

- `/admin/api/...`

Current baseline:

- `admin` may manage all admin API resources
- `project_pi` may manage project-site mappings and non-global access grants only inside explicitly granted projects
- `data_manager` may create users and manage coder/coding_tester/data_manager grants within their own grant scope via `/data-management/users`
- unit-scoped grants are created only from the admin Access Grants panel; the
  data-manager grant endpoints refuse `org_unit` scope, admins included
- `admin` may also use the data-manager user management interface with full scope access
- browser-originated mutating admin API requests require the `X-CSRFToken` header

## Important Current-State Limitation

The permission model is built around synthetic app form identity.

This matches the current single-project-first design, but it is not a good long-term fit for:

- reusable sites
- reusable form types
- deployment-based ODK mappings
- project-scoped or site-scoped access models
