---
title: Authorization Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-04-22
---

# Authorization Policy

## Purpose

This document is the normative authorization baseline for DigitVA.

Implementation must conform to this policy.

If code and policy disagree:

- review and update the policy first when behavior is intended to change
- otherwise fix code to match this document

## Core Principles

- least privilege
- explicit grants only
- no privilege broadening from filters, form IDs, or missing values
- simple is elegant
- policy first, implementation second
- one central action policy source of truth in TOML
- workflow and sync conditions stay in code as small predicates

## Decision Order

Every protected business action must be evaluated in this order:

1. the user is authenticated
2. the user is active
3. the action allows at least one of the user's roles
4. the target resource falls inside one of the user's explicit grants
5. any required workflow, sync, or ownership predicate passes

The system must fail closed.

## Role Model

DigitVA roles are:

- `admin`
- `data_manager`
- `project_pi`
- `site_pi`
- `collaborator`
- `coder`
- `coding_tester`
- `reviewer`

Roles are additive. No role implicitly inherits another role's access.

### Role meanings

- `admin`
  - global administration
  - may access all read-only data-manager reporting surfaces
- `data_manager`
  - operational triage and reporting within assigned scope
- `project_pi`
  - project-wide operational and reporting access within assigned projects
  - may perform data-manager-style submission and export actions within project scope
  - may view KPI, analytics, and CoD reporting within project scope
  - may not manage users, grants, or configuration
- `site_pi`
  - project-site operational and reporting access within assigned project-site scope
  - may perform data-manager-style submission and export actions within project-site scope
  - may view KPI, analytics, and CoD reporting within project-site scope
  - may not manage users, grants, or configuration
- `collaborator`
  - read-only scoped reporting role
  - may see analytics, KPI surfaces, and CoD reports within scope
  - may not open submissions or forms
  - may not manage users, grants, configuration, sync, or workflow actions
- `coder`
  - coding actions within scoped resources and workflow rules
- `coding_tester`
  - coding test/training actions within scoped resources and workflow rules
- `reviewer`
  - reviewer coding actions within scoped resources and workflow rules

## Scope Model

Supported authorization scope types are:

- `global`
- `project`
- `project_site`

Rules:

- `admin` uses `global`
- `project_pi` uses `project`
- `site_pi` uses `project_site`
- `data_manager` uses `project` or `project_site`
- `collaborator` uses `project` or `project_site`
- `coder`, `coding_tester`, and `reviewer` may hold `project` or `project_site` grants, but form and allocation eligibility are derived resource checks rather than top-level scope types

Form, allocation, and workflow state are not primary grant scopes.
They are resource-specific narrowing rules applied after role and grant scope.

## Action Model

Every non-public business route must map to a named action.

The central action policy is represented in TOML and must define:

- `roles`
- `resource`
- `scope`
- optional `predicate`
- mandatory `reason`

Action policy in TOML is an executable encoding of this document, not an independent policy source.

Stable action names should describe business intent rather than route paths.

Examples:

- `cod_dashboard_view`
- `dm_submission_view`
- `dm_submission_upstream_accept`
- `workflow_events_view`

## Predicate Model

Predicates are small Python checks used only when action access depends on:

- workflow state
- sync state
- allocation ownership
- similar business-state constraints

Predicates narrow access further. They do not replace role or scope checks.

Workflow and sync logic must not be moved into TOML beyond naming the predicate.

## Explanation Rule

Every action policy entry must contain a short `reason`.

The reason must explain:

- why the listed roles are allowed
- why the scope model is correct
- why a predicate is needed or not needed

## Conformance Rule

Implementation must not introduce authorization behavior that is not declared in policy.

Any policy-sensitive authorization change requires:

1. updating the policy document
2. aligning TOML
3. updating code and tests

## Settled Decisions

### Collaborator rollout

`collaborator` is part of the target role model and is limited to reporting-only access.

When implemented, collaborator access is limited to scoped reporting outputs:

- analytics
- KPI dashboards
- CoD reports

Collaborators do not get:

- form access
- submission read views
- user or grant management
- sync or workflow mutation actions

### Admin on data-manager reporting

`admin` has access to read-only data-manager reporting and analytics surfaces.

This includes:

- data-manager dashboards
- CoD dashboard reporting
- read-only analytics and export endpoints

Purely operational mutation actions remain action-specific.

### Attachment and media visibility

Attachment and media visibility should follow the visibility policy of the underlying submission.

There should not be a looser attachment-only access rule.

This policy is the target baseline. Existing routes may be migrated in a later blueprint cutover.

### Site PI scope

`site_pi` access is true `project_site` scope.

Bare `site_id` is not sufficient authorization.

If the same site exists in multiple projects, access must be evaluated against the specific `(project_id, site_id)` pair.

### Data-manager user and grant management visibility

The data-manager management surface follows these rules:

- the page shell is available to scoped data managers and admins
- grant mutation is limited to manageable scope
- returned grant records are limited to manageable scope
- user identity records may be searched and loaded to support grant assignment workflows
- out-of-scope grants must never be exposed or mutated

`project_pi`, `site_pi`, and `collaborator` do not get access to user or grant
management surfaces.

### PI operational scope

`project_pi` and `site_pi` are not reporting-only roles.

Within their explicit scope, they may use the same operational read and
data-triage surfaces as data managers, including:

- submission read views
- dashboard and KPI surfaces
- analytics
- CoD reports
- export routes
- data-manager workflow actions that operate on submissions inside scope

They do not get:

- user management
- grant management
- configuration management
- global administration

### Upstream-change naming

The canonical business action is:

- `keep current ICD while adopting latest upstream data`

The current route path `/reject-upstream-change` is treated as a backward-compatible transport name.
Its policy meaning is not "reject the update entirely."

## Initial Action Families

The first central action catalog should remain intentionally small.

Initial families:

- submission read and data-management workflow actions
- coding actions
- reviewing actions
- shared `va_form` section-render and artifact-save actions
- reporting and dashboard actions
- grant and user-management actions
- attachment and workflow history actions

For shared `va_form` routes, the policy unit is the business action, not the
partial name.

Examples:

- section rendering actions such as coding, reviewing, site-PI, and
  data-management submission views
- supporting artifact saves such as Narrative QA and Social Autopsy
- coder finalization and not-codeable submission actions

Feature toggles such as Narrative QA and Social Autopsy remain route/service
predicates driven by project-site-form configuration. They are not RBAC policy.

## Non-goals

- no external authorization service
- no DB-stored route permission matrix
- no generic policy DSL
- no blueprint-specific legacy fallback once a blueprint is migrated
