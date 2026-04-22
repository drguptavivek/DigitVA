---
title: Access Control Route Inventory
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-22
---

# Access Control Route Inventory

## Purpose

Document the current route-level access model across the Flask app before
updating grants design, policy, or implementation.

This is a current-state inventory, not a target-state recommendation.

## Core Pattern

The app now has two route-level authorization patterns:

- legacy blueprints still use `@role_required(...)`
- the first migrated slice uses `@action_authorized(...)` backed by
  `app/authz/policy.toml`

`@role_required(...)` currently enforces:

- authenticated user
- `user_status == active`
- OR-match on one of the declared roles

It does **not** enforce resource scope by itself. Scope checks happen in route
handlers, service helpers, or shared validators.

`@action_authorized(...)` enforces:

- authenticated user
- `user_status == active`
- action eligibility by role from TOML
- scope coverage from resolved resources
- optional predicate checks for workflow/sync rules

Startup now validates that migrated routes have an action mapping and that the
mapped action exists in the TOML policy registry.

Some routes still use only `@login_required`, which means they require an
authenticated session but do not require active-status or role membership.

## Current Runtime Role Detection

Current implemented role detection in `app/models/va_users.py` is uneven:

- `admin`
  - explicit active `va_user_access_grants` row with `role=admin` and
    `scope_type=global`
- `data_manager`
  - explicit project or project-site grant helpers
- `project_pi`
  - no `is_project_pi()` helper; runtime uses
    `bool(current_user.get_project_pi_projects())`
- `site_pi`
  - `is_site_pi()` is form-driven through `get_site_pi_va_forms()`
  - dashboard reporting also uses `get_site_pi_sites()`
- `collaborator`
  - present in grant enums and policy docs
  - not wired into `role_required`
  - no user helper
  - no active route usage

## Scope Shapes In Use

Current scope models seen in routes:

- `global`
  - admin-only routes and some global management/search actions
- `project`
  - project PI management
  - some coding start flows
  - data-manager project-scoped grants
- `project_site`
  - site PI reporting
  - many data-manager submission and sync actions
- `form`
  - coder/reviewer/dashboard access patterns
  - attachment access through `has_va_form_access(...)`
- `allocation`
  - coder/reviewer resume, active coding work, some reviewer views
- `self`
  - profile/session endpoints

## Blueprint Inventory

### Public and session blueprints

`va_main`, `va_auth`, `profile`, and `health` are not role-scoped business
surfaces.

- `va_main`
  - public landing page
- `va_auth`
  - public/session bootstrap with rate limits and token checks
- `profile`
  - `@login_required`
  - self-service only
- `health`
  - public health check

### Coding blueprint

Routes under `/coding` now use central action authorization backed by
`app/authz/policy.toml`.

Current scope pattern:

- dashboard and history are effectively form-scoped
- `start` is project-scoped on input, then allocation-scoped in service logic
- `resume` is allocation-scoped
- `pick` is submission/form/workflow scoped, then allocation-scoped
- `recode` appears role and workflow-window gated, with no obvious explicit
  coder/tester form-scope re-check in the workflow service
- `view/<va_sid>` is form-scoped, not allocation-scoped

Current migrated action families:

- `coding_dashboard_view`
- `coding_start`
- `coding_resume`
- `coding_pick`
- `coding_recode_start`
- `coding_demo_start`
- `coding_submission_view`
- `coding_allocation_view`
- `coding_allocation_create`
- `coding_available_view`
- `coding_stats_view`
- `coding_history_view`
- `coding_projects_view`
- `coding_admin_override_recode`
- `coding_mark_reviewer_eligible`
- `coding_debug_stats_view`

### Reviewing blueprint

Routes under `/reviewing` now use central action authorization backed by
`app/authz/policy.toml`.

Current scope pattern:

- dashboard is reviewer-form plus reviewer-language scoped
- `start` is form/language/workflow scoped, then allocation-scoped
- `resume` is allocation-scoped
- `view/<va_sid>` requires reviewer form access and an active reviewer-owned
  finalized artifact

Current migrated action families:

- `reviewing_dashboard_view`
- `reviewing_start`
- `reviewing_resume`
- `reviewing_submission_view`
- `reviewing_allocation_view`
- `reviewing_allocation_create`
- `reviewing_finalize`

### Site PI blueprint

Routes under `/sitepi` use `@role_required("site_pi")`.

Current scope pattern:

- dashboard requires at least one assigned site
- data endpoint validates requested site membership through
  `get_site_pi_sites()`

Important current limitation:

- implementation keys reporting primarily by `site_id`
- policy/grants design expects `project_site` scope
- same-site-across-multiple-projects behavior is therefore not represented
  cleanly

### Data management blueprint

Routes under `/data-management` are the first fully migrated surface.

They now use central action authorization with TOML-backed policy.

Current scope pattern:

- dashboard pages resolve scope from the user's reporting grants
- submission views and ODK edit paths are action- and resource-scoped
- CoD dashboard page now uses reporting scope, not only data-manager scope
- user/grant management mixes scoped grant controls with some global target-user
  visibility

Current user/grant management status:

- projects and project-sites are filtered to caller-manageable scope
- grant listing/create/toggle is structurally scoped through helper checks
- user search is global
- user detail returns any user object, even when only the grant subset is
  scope-filtered
- resend verification is global to any target user
- user update has uneven scope rules across fields

### `va_form` blueprint

`/vaform` is now a dynamic action-mapped surface.

Current route pattern:

- `renderpartial` uses `@login_required` plus dynamic central action
  authorization
- effective business action depends on `action`, `actiontype`, `va_partial`,
  and request method
- thin workflow/session checks still live in `validate_va_request(...)`
- `serve_attachment` and `serve_media` now use central action authorization with
  route-local file and allocation checks

Current scope pattern:

- `renderpartial`
  - mixed form, project-site, allocation, and workflow-specific access
- `serve_attachment`
  - centrally form-scoped, then file lookup and form access checks
- `serve_media`
  - centrally form-scoped, then allocation-bound for coder/reviewer and
    form-bound for admin/data-manager

Current migrated action families:

- `va_form_section_view_coding`
- `va_form_section_view_reviewing`
- `va_form_section_view_sitepi`
- `va_form_section_view_dm`
- `dm_triage_view`
- `dm_triage_save`
- `reviewing_nqa_save`
- `coding_initial_assessment_save`
- `coding_final_assessment_submit`
- `coding_not_codeable_submit`
- `submission_user_note_save`
- `workflow_history_view`
- `attachment_view`

## API Inventory

### Coding and reviewer APIs

`/api/v1/coding` and `/api/v1/reviewing` now use central action authorization
for the migrated route families.

Current notes:

- coding allocation and history endpoints are coder/tester/admin role-gated
- reviewer allocation/finalization endpoints are reviewer-only through TOML
  action policy
- state-changing routes rely on app-wide CSRF using `X-CSRFToken`

### Narrative QA and Social Autopsy APIs

`/api/v1/va/<sid>/narrative-qa` and `/api/v1/va/<sid>/social-autopsy` now use
central action authorization.

Current notes:

- they resolve submission scope centrally
- they still use route-local session and feature-toggle checks
- valid access depends on coding or reviewing allocation context from
  `va_actiontype`

### Workflow API

`/api/v1/workflow/events/<va_sid>` is now in the first migrated slice.

Current scope pattern:

- submission is resolved to project/site/form scope
- action policy allows `admin`, `data_manager`, `project_pi`, `site_pi`,
  `coder`, `coding_tester`, and `reviewer`
- resource scope is enforced centrally

### Profile API

`/api/v1/profile/*` is self-scoped and uses `@login_required`.

### ICD10 API

Current route split:

- coding ICD lookup endpoints are coder/tester/admin and allocation-bound
- data-manager ICD browser endpoints are `data_manager|admin`
- policy import/update endpoints are admin-only

## First Migrated Slice

As of `2026-04-22`, the first central-auth slice covers:

- `data_management`
- `api_v1.data_management_api`
- `api_v1.cod_buckets_api`
- `coding`
- `api_v1.coding_api`
- `va_form`
- `api_v1.nqa_api`
- `reviewing`
- `api_v1.reviewing_api`
- `api_v1.so_api`
- `api_v1.workflow`

These surfaces are governed by:

- [../policy/authorization-policy.md](../policy/authorization-policy.md)
- `app/authz/policy.toml`
- generic `/api/v1/icd10/search` is available to any authenticated user

### Analytics and DM KPI APIs

Current route split:

- `/api/v1/analytics/*` is overwhelmingly `data_manager`
- `/api/v1/analytics/mv/refresh` is `data_manager` but has system-wide side
  effects
- `/api/v1/analytics/dm-kpi/*` is `data_manager`

Current scope pattern:

- most reads expand data-manager project grants into active
  `(project_id, site_id)` pairs
- some sync-related KPI endpoints intentionally expose system-level information
  to any data manager

### CoD buckets API

Current routes:

- `/api/v1/cod-buckets/schemes`
- `/api/v1/cod-buckets/aggregates`

Current roles:

- `data_manager`
- `admin`

Current scope pattern:

- aggregation uses `dm_scoped_forms(...)` to resolve allowed forms and active
  `(project_id, site_id)` pairs
- out-of-scope `form_id` filters are rejected
- current admin behavior still depends on data-manager-style scope resolution in
  this code path

### Data-management API

Current route split:

- most routes are `data_manager`
- upstream-change and screening actions are `data_manager|admin`

Current scope pattern:

- submissions, exports, filters, coder stats, and project-site summaries are
  data-manager grant scoped
- form sync and sync preview are data-manager form scoped
- submission sync and upstream-review actions are submission scoped through
  project/project-site checks

## Current Status Summary

### What is already consistent

- `admin` is implemented as a true grant-backed global role
- `data_manager` is a first-class grant-backed role in runtime behavior
- data-manager reporting and sync flows mostly enforce explicit project or
  project-site scope
- coder/reviewer workflows mostly narrow from role -> form/language/workflow ->
  allocation
- state-changing browser JSON routes generally rely on app-wide CSRF with
  `X-CSRFToken`

### What is currently inconsistent

- `collaborator` exists in policy/grant enums but is not implemented in runtime
  route authorization
- `project_pi` has route support in admin management, but resource-scope helper
  support is uneven outside that surface
- `site_pi` policy is `project_site`, but major reporting helpers still key by
  bare `site_id`
- some routes use only `@login_required`, not `@role_required(...)`
- some attachment/media/read routes are broader than allocation-bound coding
  access
- some admin/data-manager capabilities are inconsistent about whether `admin`
  is allowed on read-only data-manager surfaces
- user-management routes under `/data-management` combine properly scoped grant
  mutation with partially global target-user visibility

## High-Signal Gaps To Resolve Before Grants Refactor

1. Decide whether route protection should standardize on `@role_required(...)`
   for all business data surfaces, replacing broad `@login_required` paths where
   appropriate.
2. Decide whether attachment access for coder/reviewer should stay form-scoped
   or return to allocation/viewability-scoped behavior.
3. Decide whether `coding.recode` must enforce the same coder/tester form scope
   as other coding entrypoints.
4. Decide whether `project_pi` and `site_pi` need first-class shared
   resource-scope helpers comparable to the data-manager helpers.
5. Decide whether `collaborator` is a real runtime role for this rollout; if
   yes, implement it end to end before documenting collaborator route access.
6. Decide whether global admin should be allowed to access all read-only
   data-manager analytics/reporting routes for consistency.
7. Decide how much of `/data-management/users` should remain globally
   targetable versus fully scoped to manageable users/grants.

## Related Files

- `app/decorators/role_required.py`
- `app/models/va_users.py`
- `app/models/va_user_access_grants.py`
- `app/routes/`
- `app/routes/api/`
- `docs/policy/access-control-model.md`
- `docs/planning/access-control-grants-design.md`
