---
title: Admin And Setup Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-11
---

# Admin And Setup Model

## Summary

The application includes a complete HTMX-driven admin UI under `/admin` for managing master data, users, access grants, ODK connections, and project configuration.

The admin panel is accessible to authenticated users with the appropriate role. Some panels are admin-only; others are accessible to project PIs for their own project scope.

Shell helpers and initialization services remain available for initial bootstrap and bulk operations, but day-to-day operational setup is now self-service through the web UI.

## Admin Panel Overview

The `/admin` interface provides the following management panels:

- **Access Grants** — manage user-to-project/site role assignments
- **Project Sites** — manage which sites are associated with a project
- **Project Forms** — per-site ODK form mapping (ODK project ID and xmlFormId), with live dropdowns populated from ODK Central via pyODK
- **Project PIs** — manage PI assignments scoped to a project
- **Projects** — project master management (create, activate, deactivate)
- **Sites** — site master management (create, activate, deactivate)
- **Users** — user account management (create, reset password, toggle active status)
- **ODK Connections** — CRUD for ODK Central connections, encrypted credential storage, test connection, and project assignment

All state-changing routes in the admin panel enforce CSRF protection via the `X-CSRFToken` request header.

### Admin-Only Panels

The following panels are restricted to application-level admins:

- ODK Connections
- Users
- Sites
- Projects

### Project-PI-Accessible Panels

Project PIs can access the following panels, scoped to their own project:

- Access Grants
- Project Sites
- Project Forms
- Project PIs

## Project Forms Panel

The Project Forms panel manages the mapping between an app project-site pair, a specific ODK Central project and form, and the VA form type used for rendering.

Key behavior:

- dropdowns for available ODK projects and forms are populated live from ODK Central via pyODK using the connection assigned to the project
- a **Form Type** dropdown lists all active form types from `mas_form_types` (e.g. `WHO_2022_VA`, `WHO_2022_VA_SOCIAL`); selecting one links that form type to the site mapping
- each project-site pair maps to at most one ODK form and at most one form type
- the mapping is stored in `map_project_site_odk` (columns: `odk_project_id`, `odk_form_id`, `form_type_id`)
- the table summary shows the configured form type as a badge next to the ODK form info; a warning badge is shown if no form type is selected

## ODK Connections Panel

The ODK Connections panel allows administrators to:

- create a new ODK Central connection (name, base URL, username, password)
- edit or delete existing connections
- test a connection against ODK Central
- assign a connection to one or more projects

Credentials (username and password) are stored encrypted in `mas_odk_connections`:

- encrypted using Fernet AES-128
- each credential field has its own per-row salt
- a shared pepper is read from the environment at runtime

Plaintext credentials are never persisted to the database.

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

The admin UI supports:

- creating and deactivating user accounts
- resetting user passwords
- assigning and revoking user access grants scoped to projects and sites

Underlying service functions remain available for shell-based operations:

- `va_user_create`
- `va_form_addform`
- `va_site_addsite`
- `va_researchproject_addproject`

## Operational Consequences

The admin UI makes the platform self-service for:

- adding and managing users
- assigning access grants
- configuring ODK connections and project-site form mappings
- managing project and site master records

Mapping spreadsheet regeneration and full platform initialization remain developer/operator tasks performed through the Flask shell.
