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
- stale coding allocations older than one hour are cleared before new allocation

Coding steps:

- initial assessment creates a `va_initial_assessments` row
- final coding creates a `va_final_assessments` row
- not-codeable path creates a `va_coder_review` row

Completion behavior:

- final coding or not-codeable submission deactivates the active coding allocation

Recode:

- the app can deactivate existing active coding artifacts and reopen a submission for fresh coding

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

### Current permission helpers

The user model provides helpers such as:

- `is_coder()`
- `is_reviewer()`
- `is_site_pi()`
- `get_coder_va_forms()`
- `get_reviewer_va_forms()`
- `has_va_form_access()`

### Current effective model

Permissions are currently form-centric.

For example:

- `permission["coder"]` contains the app form ids the coder can access
- direct route access also checks the submission's `va_form_id` against user access

### Language as second filter

Visibility is also filtered by:

- `current_user.vacode_language`

So a coder may have form access but still not see a submission if the narration language does not match profile settings.

## Route-Level Validation

The main route guard is:

- [`va_validate_permissions`](C:\workspace\DigitVA\app\decorators\va_validate_permissions.py)

It validates:

- dashboard access by role
- coding and review action URLs
- submission access based on current user's form permissions and workflow state

## Important Current-State Limitation

The permission model is built around synthetic app form identity.

This matches the current single-project-first design, but it is not a good long-term fit for:

- reusable sites
- reusable form types
- deployment-based ODK mappings
- project-scoped or site-scoped access models
