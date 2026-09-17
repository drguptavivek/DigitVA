---
title: Admin API Access Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-17
---

# Admin API Access Policy

## Purpose

DigitVA exposes a dedicated `/admin` blueprint for master-data and authorization administration.

This blueprint is API-oriented so it can support HTMX, React, or other browser clients without tying administration to server-rendered workflow routes.

## Route Family

Administrative JSON routes live under:

- `/admin/api/...`

These routes are separate from workflow routes under:

- `/vaapi/...`
- `/vacta/...`
- `/vadashboard/...`

## CSRF Baseline

CSRF protection is enabled application-wide for browser-originated mutating requests.

Mutating `/admin/api` requests must send the CSRF token in this header:

- `X-CSRFToken`

Returning JSON does not exempt a route from CSRF protection.

## Admin API Roles

The admin API may be used by:

- `admin`
- `project_pi`

No other role may call `/admin/api` routes.

## Scope Rules

### `admin`

`admin` may manage:

- all projects
- all sites
- all project-site mappings
- all access grants

### `project_pi`

`project_pi` may manage data only inside explicitly granted projects.

`project_pi` may:

- list accessible projects
- list accessible sites and project-site mappings
- create or reactivate project-site mappings for assigned projects
- create, view, and deactivate non-global access grants inside assigned projects

`project_pi` may not:

- create or deactivate `admin` grants
- create or deactivate `project_pi` grants
- manage data outside assigned projects

## Grant Rules

Grant writes through `/admin/api` must remain explicit.

Required rules:

- broad access must never be inferred from missing values
- scope must always be declared explicitly
- writes should be idempotent when the same mapping or grant is submitted again
- deactivation should be logical, not destructive

## Mapping Rules

Project-site mapping writes through `/admin/api` must:

- validate that the project exists
- validate that the site exists
- remain scoped to the caller's allowed project set
- reactivate an existing inactive mapping rather than creating duplicates

### ODK form uniqueness

An ODK Central form — identified by `(ODK connection, odk_project_id, odk_form_id)` —
may be mapped to at most one `(project_id, site_id)` pair. Mapping it twice makes sync
pull the same form under two projects.

Required behavior:

- `POST /admin/api/projects/<project_id>/odk-site-mappings` rejects with `400` when the
  ODK form is already mapped to a different project-site on the same connection, naming
  that project-site
- re-saving the same project-site with the same ODK form stays idempotent (`200`)
- scope is per ODK connection: the connection is resolved through `map_project_odk`, so
  the same ODK ids on a different connection are a different form and are allowed
- a project with no `map_project_odk` row has no connection and therefore no conflict
  scope; its mappings are inert because sync cannot run for them
- a mapping on a **deactivated** project-site still blocks. Sync keys off the mapping,
  not the pair status, so the remedy is to delete the stale mapping
- `GET /admin/api/odk-connections/<connection_id>/odk-projects/<odk_project_id>/forms`
  annotates each form with `mapped_to` (`project_id`, `site_id`, `same_target`) when the
  optional `project_id`/`site_id` query params name the pair being configured, so the
  admin picker can disable forms owned by another pair
- `GET /admin/api/odk-site-mappings/conflicts` lists ODK forms mapped more than once,
  marking which targets may be removed and which need a manual decision
- `DELETE /admin/api/projects/<project_id>/odk-site-mappings/<site_id>` deliberately does
  **not** require the project, site, or pair to be active: a stale mapping on a
  deactivated pair must stay deletable
- `flask odk-mappings audit [--fix]` performs the same audit offline
  (see [`docs/current-state/cli-reference.md`](../current-state/cli-reference.md))
