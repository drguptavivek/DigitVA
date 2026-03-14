---
title: Workflow And Permissions
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-14
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

The current workflow is built around form-based permissions and per-submission allocation.

An additive canonical workflow-state table now exists:

- `va_submission_workflow`

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

## Main Workflow Sequence

1. ODK sync writes or updates `va_submissions`.
2. Eligible submissions become visible in role dashboards.
3. A user starts coding or review, which creates an allocation.
4. The user works through the category UI and submits outcomes.
5. The allocation is released when work is completed or a terminal workflow decision is recorded.

## Coder Workflow

Project-level intake setting:

- `va_project_master.coding_intake_mode`
- supported values:
  - `random_form_allocation`
  - `pick_and_choose`

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

Entry variants:

- `vastartcoding` picks from only the coder-accessible projects configured for
  `random_form_allocation`
- `vapickcoding` is available only for ready submissions in coder-accessible
  projects configured for `pick_and_choose`

Coding steps:

- initial assessment creates a `va_initial_assessments` row
- initial assessment also records `coder_step1_saved` in `va_submission_workflow`
- final coding creates a `va_final_assessments` row
- final coding also records `coder_finalized` in `va_submission_workflow`
- not-codeable path creates a `va_coder_review` row
- coder Not Codeable also records `not_codeable_by_coder` in
  `va_submission_workflow`
- when a coder marks a case Not Codeable, DigitVA saves the local outcome first
  and then separately attempts to push `hasIssues` review state to ODK Central

Completion behavior:

- final coding or not-codeable submission deactivates the active coding allocation

Timeout cleanup:

- the app still performs a stale-allocation release check when a coder starts
  normal coding
- a Celery beat task also runs every hour to release stale coding allocations
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

Canonical state values currently written in the runtime path include:

- `ready_for_coding`
- `coding_in_progress`
- `coder_step1_saved`
- `coder_finalized`
- `not_codeable_by_coder`

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

Data-manager triage:

- the `Data Triage` panel can mark a submission Not Codeable only while the
  canonical workflow state is:
  - `screening_pending`
  - `ready_for_coding`
  - `not_codeable_by_data_manager`
- a successful triage write creates or updates `va_data_manager_review`
- the canonical workflow state is updated to `not_codeable_by_data_manager`
- coder availability excludes those submissions automatically because coder pool
  selection now requires `ready_for_coding`

Audit trail:

- coder workflow milestones are recorded in `va_submissions_auditlog`
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

- the app creates a reviewing allocation

Review submission:

- the reviewer submits a `va_reviewer_review` record
- the active reviewing allocation is then released

## Site PI Behavior

Site PI currently has a reporting-oriented dashboard rather than a full operational workflow.

Current site PI capabilities:

- site-level KPI viewing
- coder participation and coding status reporting
- some access-controlled view/recode paths depending on workflow state

Important note:

- current Site PI logic mixes site and form assumptions in places and should be treated carefully when refactoring

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
- browser-originated mutating admin API requests require the `X-CSRFToken` header

## Important Current-State Limitation

The permission model is built around synthetic app form identity.

This matches the current single-project-first design, but it is not a good long-term fit for:

- reusable sites
- reusable form types
- deployment-based ODK mappings
- project-scoped or site-scoped access models
