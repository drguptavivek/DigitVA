---
title: Admin And Setup Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-09
---

# Admin And Setup Model

## Summary

The current application does not expose a full server-rendered web-admin interface for managing master data.

Operational setup is done mainly through:

- Flask shell functions
- initialization services
- mapping refresh services

An additive JSON admin API now also exists under:

- `/admin/api/...`

The frontend is focused on workflow execution, not system administration.

## What Exists In The Web UI

Current frontend pages cover:

- login
- coder dashboard
- reviewer dashboard
- site PI dashboard
- profile and password update
- coding and review forms

What is not present in the current frontend:

- add project UI
- add site UI
- add form UI
- add coder/user UI
- ODK connection management UI
- mapping file management UI

The current `/admin/api` work is API-first for future HTMX or React clients rather than a complete built-in admin frontend.

## Current Setup Path

The main operational shell helpers are exposed in:

- [`run.py`](../../run.py)

Important shell operations include:

- `va_db_initialise_researchprojects()`
- `va_db_initialise_researchsites()`
- `va_db_initialise_vaforms()`
- `va_db_initialise_vausers()`
- `va_mapping_icd()`
- `va_mapping_fieldsitepi()`
- `va_mapping_fieldcoder()`
- `va_mapping_choice()`
- `va_mapping_summary()`
- `va_mapping_summaryflip()`
- `va_mapping_info()`
- `va_mapping_flip()`
- `va_data_sync_odkcentral()`

## Full Initialization Flow

The shell helper `va_initialise_platform()` currently performs:

1. database backup creation
2. full schema drop and recreate
3. seed project, site, and form master data
4. load ICD codes
5. generate mapping Python modules from spreadsheets
6. perform ODK sync
7. initialize users

This reflects the current one-project-first bootstrap model.

## Mapping Administration

Mapping spreadsheets are stored under:

- `resource/mapping`

The app does not read them dynamically from the UI on every request.

Instead, service functions read the spreadsheets and generate Python modules under:

- `app/utils/va_mapping`

This is currently an operational/admin task, not a user-facing feature.

## User And Access Administration

Current user, form, site, and project CRUD-like operations exist as service functions only.

Examples:

- `va_user_create`
- `va_form_addform`
- `va_site_addsite`
- `va_researchproject_addproject`

These are intended to be invoked from Flask shell or internal admin workflows, not from current templates.

The current additive `/admin/api` layer now exposes a narrower runtime surface for:

- listing projects, sites, and project-site mappings
- listing users for grant assignment
- listing active access grants
- creating or reactivating project-site mappings
- creating or deactivating access grants

This admin API is protected by authentication, role checks, project scoping, and application-wide CSRF protection.

## Operational Consequences

Current setup and admin behavior implies:

- platform changes require operator/developer involvement
- onboarding new forms or users is not self-service through the app
- ODK connection details are not managed in the UI
- the app behaves more like a configured workflow system than a self-administered multi-tenant platform
