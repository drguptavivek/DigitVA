---
title: Admin API Access Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-09
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
