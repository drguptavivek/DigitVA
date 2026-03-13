---
title: Workflow And Permissions
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-13
---

# Workflow And Permissions

## Summary

After sync, the application runs a role-based workflow over `va_submissions`.

Primary roles:

- coder
- reviewer
- site PI

The current workflow is built around form-based permissions and per-submission allocation.

## Main Workflow Sequence

1. ODK sync writes or updates `va_submissions`.
2. Eligible submissions become visible in role dashboards.
3. A user starts coding or review, which creates an allocation.
4. The user works through the category UI and submits outcomes.
5. The allocation is released when work is completed or a terminal workflow decision is recorded.

## Coder Workflow

Coder dashboard behavior:

- the coder sees submissions only if:
  - the submission's `va_form_id` is in the coder's permitted forms
  - the submission language is in the coder's allowed languages
  - the submission is not already in an excluded terminal or allocated state

Starting coding:

- the app creates a `va_allocations` row for the chosen submission
- stale coding allocations older than one hour are released automatically
- the release path deactivates only the stale coding allocation
- any saved `va_initial_assessments` row is preserved so the coder can resume
  final COD later

Coding steps:

- initial assessment creates a `va_initial_assessments` row
- final coding creates a `va_final_assessments` row
- not-codeable path creates a `va_coder_review` row

Completion behavior:

- final coding or not-codeable submission deactivates the active coding allocation

Timeout cleanup:

- the app still performs a stale-allocation release check when a coder starts
  normal coding
- a Celery beat task also runs every hour to release stale coding allocations
- timeout release writes a `va_submissions_auditlog` row with
  `va_allocation_released_due_to_timeout`
- timeout release does not discard saved initial COD work

Recode:

- the app can deactivate existing active coding artifacts and reopen a submission for fresh coding

### Coding Screen Left Navigation

The coder/reviewer left navigation in `va_coding.html` is currently driven by the
stored `va_submissions.va_category_list` value, not by dynamic template inspection of
raw submission data.

Current flow:

1. sync/preprocessing computes `va_category_list`
2. `va_cta` passes that list to the coding page as `catlist`
3. most category buttons render only if their hardcoded category code is present in `catlist`
4. previous/next category navigation also uses the same stored list

Current visibility patterns:

- most categories are guarded by `"<category_code>" in catlist`
- `vainterviewdetails` adds a second gate and only shows for `va_action == "vasitepi"`
- `vanarrationanddocuments` is always shown in the left nav and is not guarded by `catlist`
- `catcount` drives badge counts only; it does not control visibility

Important limitation:

- category visibility is determined at preprocess time and stored
- category content is recalculated again at render time
- this means nav visibility and actual rendered content can drift if mappings or filters change after sync

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
