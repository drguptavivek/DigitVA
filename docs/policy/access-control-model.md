---
title: Access Control Model
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-09
---

# Access Control Model

## Core Rule

DigitVA uses a hybrid RBAC and ABAC model.

- role defines capability
- scope defines boundary
- access is granted only when both match

In other words:

- RBAC answers: what can this user do?
- ABAC answers: where can this user do it?

## Roles

DigitVA uses these roles:

- `admin`
- `project_pi`
- `site_pi`
- `collaborator`
- `coder`
- `reviewer`

Roles are additive and do not inherit from each other.

## Role Meaning

### `admin`

Global administration.

May manage:

- users
- projects
- sites
- project-site mappings
- integrations
- all application records

### `project_pi`

Project-wide oversight within assigned projects.

May:

- view data across all assigned sites in an assigned project
- view reporting for an assigned project
- perform oversight actions allowed by workflow policy

### `site_pi`

Site-specific oversight within assigned project-site scope.

May:

- view data for assigned sites within assigned projects
- view reporting for assigned project-site scope
- perform oversight actions allowed by workflow policy

A user may hold `site_pi` grants for many project-site pairs.

### `collaborator`

Read-only role within assigned scope.

May:

- view data
- view reporting

May not:

- code
- review
- perform oversight write actions
- administer configuration

### `coder`

Coding role within assigned scope.

May:

- start coding
- resume owned coding
- submit coding outcomes
- view coding records when allowed by workflow policy

### `reviewer`

Review role within assigned scope.

May:

- start review
- resume owned review
- submit review outcomes
- view review records when allowed by workflow policy

## Scope Model

Authorization scope must be explicit.

Supported scope types:

- `global`
- `project`
- `project_site`

Rules:

- `global` means system-wide access
- `project` means access across all sites within that project
- `project_site` means access only to one site within one project

Broad access must be granted explicitly.

The system must not infer broader access from missing values or partial keys.

## Role To Scope Rules

- `admin` uses `global`
- `project_pi` uses `project`
- `site_pi` uses `project_site`
- `collaborator` uses `project` or `project_site`
- `coder` uses `project` or `project_site`
- `reviewer` uses `project` or `project_site`

## Authorization Rule

A request is allowed only if:

1. the user is authenticated and active
2. the user has the required role for the action
3. the target record falls inside one of the user's explicit grants
4. workflow-specific constraints also pass

Workflow-specific constraints may include:

- allowed language
- workflow state
- allocation ownership
- terminal status checks

These constraints narrow access further, but they do not replace role and scope checks.

## Examples

### Example 1

- user role: `coder`
- user grant: `project_site(UNSW01, NC01)`
- submission scope: `project_site(UNSW01, NC01)`

Result:

- allowed to code, if workflow rules also allow it

### Example 2

- user role: `coder`
- user grant: `project_site(UNSW01, NC01)`
- submission scope: `project_site(UNSW01, TR01)`

Result:

- denied, because scope does not match

### Example 3

- user role: `coder`
- user grant: `project(UNSW01)`
- submission scope: `project_site(UNSW01, TR01)`

Result:

- allowed, because the explicit grant covers the whole project

### Example 4

- user role: `site_pi`
- user grants:
  - `project_site(UNSW01, NC01)`
  - `project_site(ICMR01, NC01)`

Result:

- the user may see site `NC01` data in both assigned projects
- the user may not see other sites in those projects unless separately granted

### Example 5

- user role: `project_pi`
- user grant: `project(UNSW01)`

Result:

- the user may see data across all sites in `UNSW01`

## What Is Not A Scope

These must not be the long-term authorization boundary:

- synthetic `va_form_id`
- encoded business identifiers
- ODK project id
- ODK form id

Those values may help resolve context, but they are not the access boundary.

## Grant Storage Baseline

Permission data should be stored as explicit user-role-scope assignments.

Recommended shape:

- `user_id`
- `role`
- `scope_type`
- `project_id`
- `site_id`

Rules:

- `scope_type = global` is valid only for global roles such as `admin`
- `scope_type = project` requires `project_id`
- `scope_type = project_site` requires both `project_id` and `site_id`
- `site_id = NULL` must not imply project-wide access unless `scope_type = project`

This is preferred over loosely structured JSON.

## Migration Rule

Current permissions are legacy and inconsistent:

- coder and reviewer permissions are currently form-centric
- Site PI behavior mixes form and site assumptions

Migration policy:

1. resolve each legacy permission to its real project and site
2. map legacy Site PI access into explicit `site_pi` or `project_pi` grants
3. map read-only access into `collaborator` grants where applicable
4. store future access using explicit role and explicit scope type
5. do not carry forward ambiguous permissions

## Implementation Baseline

Implementation should separate:

- role check
- scope check
- workflow state check

They should not remain blended together behind form-id-based helpers.

## API And CSRF Baseline

Authorization services should be reusable across server-rendered, HTMX, and React clients.

Rules:

- state-changing browser requests must be served by API-capable routes or thin route handlers that call shared authorization services
- HTMX and React clients must not have separate authorization logic
- browser-originated state-changing requests must enforce CSRF protection, even when the route returns JSON
- the required CSRF header name is `X-CSRFToken`
- GET routes may stay read-only and must not be used as a shortcut for mutation
