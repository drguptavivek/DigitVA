---
title: Admin And Setup Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-31
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
- **Languages** — canonical language list management with ODK alias mapping. Shows unmapped language values found in submissions.

All state-changing routes in the admin panel enforce CSRF protection via the `X-CSRFToken` request header.

### Admin-Only Panels

The following panels are restricted to application-level admins:

- ODK Connections
- Users
- Sites
- Projects
- Languages

### Project-PI-Accessible Panels

Project PIs can access the following panels, scoped to their own project:

- Access Grants
- Project Sites
- Project Forms
- Project PIs

Current grant roles include:

- `admin`
- `project_pi`
- `site_pi`
- `coder`
- `reviewer`
- `data_manager`
- `collaborator`

Current scope rules include:

- `data_manager` may be granted at `project` or `project_site`

## Project Master

Current project master data now includes:

- project identity fields
- active/inactive status
- Narrative Quality Assessment enablement
- coding intake mode (`random_form_allocation` or `pick_and_choose`)

Current admin behavior:

- the Projects panel can edit `coding_intake_mode`
- new projects default to `random_form_allocation`

## Project Forms Panel

The Project Forms panel manages the mapping between an app project-site pair, a specific ODK Central project and form, and the VA form type used for rendering.

Key behavior:

- the site table renders immediately from local DB state
- ODK project and form dropdowns are populated lazily from ODK Central only
  when an operator opens a site's Configure row
- live ODK dropdown fetches now respect the shared ODK connection guard
  state, so cooldown/failure messages are surfaced inline instead of leaving
  the whole panel blocked
- a **Form Type** dropdown lists all active form types from `mas_form_types` (e.g. `WHO_2022_VA`, `WHO_2022_VA_SOCIAL`); selecting one links that form type to the site mapping
- each project-site pair maps to at most one ODK form and at most one form type
- the mapping is stored in `map_project_site_odk` (columns: `odk_project_id`, `odk_form_id`, `form_type_id`)
- the table summary shows the configured form type as a badge next to the ODK form info; a warning badge is shown if no form type is selected
- the connection bar now shows the assigned connection's current cooldown or
  recent failure state so operators can see degraded ODK health before trying
  more live lookups

## ODK Connections Panel

The ODK Connections panel allows administrators to:

- create a new ODK Central connection (name, base URL, username, password)
- edit or delete existing connections
- test a connection against ODK Central
- assign a connection to one or more projects
- inspect shared connection-health state such as:
  - cooldown active/until
  - recent retryable failure count
  - recent failure message

Credentials (username and password) are stored encrypted in `mas_odk_connections`:

- encrypted using Fernet AES-128
- each credential field has its own per-row salt
- a shared pepper is read from the environment at runtime

Plaintext credentials are never persisted to the database.

Current operational behavior:

- each DB-managed ODK connection also stores shared guard state used by both
  app requests and background workers
- admin connection tests and live ODK lookups fail fast while a connection is
  in cooldown
- the same connection guard is used by sync and ODK write-back flows

## Languages Panel

The Languages panel manages the canonical language list and ODK alias mappings used throughout the application.

### Data Model

- **`mas_languages`** — canonical language list with `language_code` (PK), `language_name`, and `is_active` flag
- **`map_language_aliases`** — maps raw ODK field values to canonical codes (e.g., `"bn"` → `"bangla"`, `"Bengali"` → `"bangla"`)

### Key Behavior

- the panel lists all canonical languages with their aliases and submission counts
- admins can create, edit (rename/update aliases), and toggle languages active/inactive
- **unmapped values alert**: the panel detects language values in `va_submissions` that don't match any alias and displays them prominently so the admin can add them
- aliases can be added or removed inline; the language code itself is always kept as an alias
- alias conflicts across languages are prevented (one alias maps to exactly one language)
- deactivated languages are hidden from coder profile language selection but existing data is preserved

### Sync Integration

- during ODK sync, raw `narr_language` / `language` values are normalized to canonical codes via `_normalize_language()` before storage
- the alias lookup is cached per sync run (cleared at start of each run)
- unknown values (no matching alias) pass through unchanged and appear in the unmapped alert

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/api/languages` | List languages (optional `include_inactive`, `include_unmapped`) |
| POST | `/admin/api/languages` | Create new language with aliases |
| PUT | `/admin/api/languages/<code>` | Update name and/or aliases |
| POST | `/admin/api/languages/<code>/toggle` | Toggle active/inactive |
| DELETE | `/admin/api/languages/<code>/aliases/<alias>` | Remove a single alias |

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

## Form Type Bootstrap

The field-mapping admin panel depends on rows in `mas_form_types`.

Operational baseline:

- seeded languages do not imply seeded form types
- the Languages panel may be populated while the field-mapping panel still shows no form types
- the default `WHO_2022_VA` form type and its mappings are bootstrapped by the seed command, not by the Languages panel

If `/admin/?panel=%2Fadmin%2Fpanels%2Ffield-mapping` shows:

- `No form types registered yet. Click New Form Type to create one.`

the standard recovery path is:

```bash
docker compose exec minerva_app_service uv run flask seed run
```

Current behavior of that command for field mapping bootstrap:

- registers `WHO_2022_VA` in `mas_form_types` if missing
- migrates the default WHO 2022 category, field, and choice mappings from:
  - `resource/mapping/mapping_labels.xlsx`
  - `resource/mapping/mapping_choices.xlsx`
- safely skips languages and the default admin user if they already exist

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
