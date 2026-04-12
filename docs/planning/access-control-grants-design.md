---
title: Access Control Grants Technical Design
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-04-12
---

# Access Control Grants Technical Design

## Purpose

This document turns the access-control policy baseline into a concrete schema and migration design.

It defines:

- the target grants table
- how roles and scopes are represented
- how current legacy permissions migrate into grants
- how runtime authorization should evaluate grants
- how admin APIs should write explicit grants and project-site mappings

This design follows [../policy/access-control-model.md](../policy/access-control-model.md).

## Design Summary

DigitVA should stop using `va_users.permission` as the long-term source of truth for authorization scope.

Instead, authorization should use explicit grant rows.

Each grant represents:

- one user
- one role
- one explicit scope

Administrative mutation for project-site mappings and grants should live under a dedicated `/admin/api` route family rather than the workflow-oriented `va_api` blueprint.

The auth foundation should be introduced in this order:

- standalone project master
- standalone site master
- project-site membership
- user access grants

## Target Roles

The target role set is:

- `admin`
- `project_pi`
- `site_pi`
- `collaborator`
- `coder`
- `coding_tester`
- `reviewer`

## Target Scope Types

The target scope types are:

- `global`
- `project`
- `project_site`

Scope semantics:

- `global` means system-wide access
- `project` means all sites within one project
- `project_site` means one site within one project

Broad access must always be explicit.

## Recommended Schema

### `va_project_master`

Suggested fields:

- `project_id`
- `project_code`
- `project_name`
- `project_nickname`
- `project_status`
- `project_registered_at`
- `project_updated_at`

Purpose:

- standalone reusable project identity for future auth and onboarding logic

### `va_site_master`

Suggested fields:

- `site_id`
- `site_name`
- `site_abbr`
- `site_status`
- `site_registered_at`
- `site_updated_at`

Purpose:

- standalone reusable site identity

### `va_project_sites`

Suggested fields:

- `project_site_id`
- `project_id`
- `site_id`
- `project_site_status`
- `project_site_registered_at`
- `project_site_updated_at`

Purpose:

- explicit membership of a site in a project
- future source of truth for project-site scoped authorization

### `va_user_access_grants`

Suggested fields:

- `grant_id`
- `user_id`
- `role`
- `scope_type`
- `project_id`
- `project_site_id`
- `grant_status`
- `created_at`
- `updated_at`
- `created_by`
- `updated_by`
- `notes`

### Foreign keys

- `user_id` -> `va_users.user_id`
- `project_id` -> `va_project_master.project_id`
- `site_id` -> `va_site_master.site_id`
- `project_site_id` -> `va_project_sites.project_site_id`

`va_project_sites` should have a unique `(project_id, site_id)` constraint.

### Enums

#### `role`

Allowed values:

- `admin`
- `project_pi`
- `site_pi`
- `collaborator`
- `coder`
- `coding_tester`
- `reviewer`

#### `scope_type`

Allowed values:

- `global`
- `project`
- `project_site`

#### `grant_status`

Allowed values:

- `active`
- `inactive`

## Scope Validation Rules

### `global`

Required:

- `scope_type = global`
- `project_id IS NULL`
- `project_site_id IS NULL`

Allowed roles:

- `admin`

### `project`

Required:

- `scope_type = project`
- `project_id IS NOT NULL`
- `project_site_id IS NULL`

Allowed roles:

- `project_pi`
- `collaborator`
- `coder`
- `coding_tester`
- `reviewer`

### `project_site`

Required:

- `scope_type = project_site`
- `project_id IS NULL`
- `project_site_id IS NOT NULL`

Allowed roles:

- `site_pi`
- `collaborator`
- `coder`
- `coding_tester`
- `reviewer`

## Recommended Constraints

### Check constraints

Add checks so invalid grant shapes cannot be stored.

Required checks:

1. `global` grants must have both `project_id` and `project_site_id` null.
2. `project` grants must have `project_id` present and `project_site_id` null.
3. `project_site` grants must have `project_site_id` present and `project_id` null.
4. `admin` may only use `global`.
5. `project_pi` may only use `project`.
6. `site_pi` may only use `project_site`.

### Uniqueness

Recommended unique key:

- project-scope uniqueness should be enforced separately from project-site uniqueness because nullable columns weaken a single composite unique key in PostgreSQL

This prevents duplicate active grants for the same scope.

### Indexes

Recommended indexes:

- `(user_id, grant_status)`
- `(role, grant_status)`
- `(scope_type, project_id, project_site_id, grant_status)`
- `(project_id, grant_status)`
- `(project_site_id, grant_status)`

## Why A Grants Table Is Preferred

Compared with JSON in `va_users.permission`, a grants table is better because it is:

- explicit
- queryable
- indexable
- auditable
- constraint-friendly
- easier to migrate safely

This matters because the target model needs project and project-site scope, not just form lists.

## Current Legacy Model

Current state:

- `va_users.permission` stores JSON keyed by role
- coder and reviewer entries are validated against `va_forms.form_id`
- Site PI entries are ambiguous in practice and are sometimes treated as site ids

Current examples:

- `permission["coder"] = ["UNSW01NC0101"]`
- `permission["reviewer"] = ["UNSW01NC0101"]`
- `permission["sitepi"] = [...]`

The current model is not safe to carry forward because the same storage shape is being interpreted in different ways.

## Migration Design

### Phase 1: Add grants table

Create `va_project_master`, `va_site_master`, `va_project_sites`, and `va_user_access_grants` without removing `va_users.permission`.

During this phase:

- keep current behavior operational
- do not cut over runtime authorization yet
- backfill project master from current `va_research_projects`
- backfill site master and project-site rows from current `va_sites`
- do not backfill grants yet

Migration note:

- if PostgreSQL UUID generation is needed inside SQL backfill, enable `pgcrypto` with `CREATE EXTENSION IF NOT EXISTS pgcrypto`

### Phase 2: Validate new foundation tables

Validate:

- `va_project_master` rows match current projects
- `va_site_master` rows match current sites
- `va_project_sites` rows match current project-site memberships

Grant backfill should not start until these tables are validated.

### Phase 3: Build legacy permission classifier

Define deterministic mapping rules for each legacy permission entry.

#### Legacy coder and reviewer

For each legacy form id:

1. load `va_forms` by `form_id`
2. resolve `project_id`
3. resolve `site_id`
4. resolve or create `project_site_id`
5. create a grant

Recommended default mapping:

- one legacy coder form permission -> one `coder` `project_site` grant
- one legacy reviewer form permission -> one `reviewer` `project_site` grant

Important:

- if multiple legacy form ids collapse to the same project-site pair, deduplicate them into one project-site grant

### Phase 4: Classify legacy Site PI access

Legacy Site PI permissions must not be migrated blindly.

For each legacy `sitepi` entry:

1. determine whether the value is a site id or a form id
2. resolve it to a real `(project_id, site_id)` or `project_id`
3. choose target role:
   - `site_pi` for project-site oversight
   - `project_pi` only if the intended business meaning is explicitly project-wide

If classification is ambiguous:

- do not auto-broaden access
- mark the record for manual review

### Phase 5: Add compatibility resolver

Before full cutover, add a compatibility layer that can evaluate access from:

- new grants first
- legacy `va_users.permission` second

This allows staged rollout without breaking current users immediately.

### Phase 6: Backfill grants

Backfill grants only after foundation validation.

Requirements:

- idempotent writes
- no implicit privilege broadening
- unresolved entries reported for manual review

Current first pass:

- treat the current operational backfill as `UNSW01` only
- backfill only unambiguous coder grants
- backfill known `UNSW01` PI grants by explicit named assignments
- backfill known `UNSW01` reviewer grants by explicit named project-site assignments
- skip non-`UNSW01` legacy permissions for now
- skip any remaining non-`UNSW01` or unresolved reviewer/Site PI cases until policy mapping is finalized

### Phase 7: Cut over authorization

Update authorization helpers and guards so they use grants as the source of truth.

After cutover:

- new access assignments must write grants
- `va_users.permission` becomes legacy-read-only

### Phase 8: Retire legacy permission storage

After validation:

- stop reading `va_users.permission` for authorization
- remove legacy validators that treat permissions as `va_forms.form_id` lists
- keep migration audit records

## Mapping Examples

### Example 1: coder

Current:

- user has `permission["coder"] = ["UNSW01NC0101", "UNSW01NC0102"]`

Resolved:

- both form ids map to `(UNSW01, NC01)`

Target:

- one `coder` grant with `scope_type = project_site`, `project_id = UNSW01`, `site_id = NC01`

### Example 2: reviewer across a full project

Current:

- no reliable legacy representation exists

Target:

- one explicit `reviewer` grant with `scope_type = project`, `project_id = UNSW01`

This is an example of why the grants table is needed. The legacy model cannot express this cleanly.

### Example 3: site PI for same site in multiple projects

Target grants:

- `site_pi`, `project_site`, `project_site_id=<UNSW01/NC01 row>`
- `site_pi`, `project_site`, `project_site_id=<ICMR01/NC01 row>`

This allows one user to oversee the same site code in multiple projects without implying access to other sites.

## Runtime Authorization Design

Authorization should evaluate in this order:

1. authenticate user
2. verify user status is active
3. verify required role for the requested action
4. resolve the target resource to `project_id` and `project_site_id`
5. load matching active grants for the user and role
6. evaluate whether one of those grants covers the resource
7. apply workflow-specific checks

### Coding Gate Design

For non-demo coding workflows, apply project-site coding gates in UTC:

- `coding_enabled`
- `coding_start_date`
- `coding_end_date`
- `daily_coder_limit`

Role-specific behavior:

- `coder`: all non-demo coding gates are enforced
- `coding_tester`: all four non-demo coding gates are bypassed for testing

Demo/training exception:

- `demo_training_enabled` projects are intentionally open to all active
  authenticated users through the demo coding path
- this open access does not broaden non-demo coding authorization

## API Route Direction

Authorization logic should be consumed through API-oriented route handlers and shared services, not embedded only in server-rendered page routes.

That means:

- HTMX flows should call API-backed endpoints or thin server routes that delegate to the same authorization services
- future React clients should use the same API contract and authorization checks
- permission decisions should live in reusable service logic, not UI-specific view code

### CSRF requirement

API-style routes used by browser clients must still enforce CSRF protection for state-changing requests.

Rules:

- HTMX requests that mutate state must include a valid CSRF token in the `X-CSRFToken` header
- React requests that rely on cookie-based session auth must include a valid CSRF token in the `X-CSRFToken` header
- read-only GET endpoints may remain exempt if they do not mutate state
- CSRF protection must not be dropped simply because a route returns JSON instead of HTML

Coverage rules:

- `global` grant covers all resources
- `project` grant covers any resource in that project
- `project_site` grant covers only that exact `project_site_id`

## Implementation Direction

Current helpers are form-centric and should be replaced over time.

Target helper shapes:

- `user_has_role(user, role)`
- `user_has_scope(user, role, project_id, site_id)`
- `authorize_submission_action(user, role, submission, action)`

These should be implemented separately from workflow-state helpers such as allocation and reviewed/not-reviewed checks.

## Data Safety Rules

During migration:

- never delete `va_users.permission` before grant backfill is validated
- do not broaden permissions automatically when source data is ambiguous
- preserve a migration report for every user showing old values and new grants
- require manual review for unresolved Site PI mappings

## Open Questions

These should be settled before implementation begins:

- do we need a separate audit table for grant history, or are timestamps on the grants table enough for first pass?
- should collaborators be allowed to view attachments and narration audio by default, or should those be a separate capability decision?
- should project-wide coder and reviewer grants be allowed immediately, or introduced only after the project-site refactor is complete?

## Immediate Next Step

Implement the schema migration for `va_user_access_grants` and write a backfill script that outputs:

- created grants
- deduplicated grants
- ambiguous legacy entries requiring manual review
