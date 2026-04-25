---
title: Admin And Setup Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-25
---

# Admin And Setup Model

## Summary

The application includes a complete HTMX-driven admin UI under `/admin` for managing master data, users, access grants, ODK connections, and project configuration.

The admin route layer is package-based: [app/routes/admin.py](../../app/routes/admin.py) owns only the shared `admin` blueprint and section registration, while request guards and extracted route branches live under [app/routes/admin_sections](../../app/routes/admin_sections). App-wide HTTP helpers live under [app/http](../../app/http), shared grant/scope/request-context helpers live under [app/authz](../../app/authz), and response serializers live under [app/serializers](../../app/serializers). The remaining flat admin section modules are `shell.py`, `projects.py`, `sites.py`, and `project_pis.py`. Admin subtree packages now cover [users](../../app/routes/admin_sections/users), [access_grants](../../app/routes/admin_sections/access_grants), [project_forms](../../app/routes/admin_sections/project_forms), [project_sites](../../app/routes/admin_sections/project_sites), [odk_connections](../../app/routes/admin_sections/odk_connections), [languages](../../app/routes/admin_sections/languages), [activity](../../app/routes/admin_sections/activity), [cod_buckets](../../app/routes/admin_sections/cod_buckets), [icd10_browser](../../app/routes/admin_sections/icd10_browser), [field_mapping](../../app/routes/admin_sections/field_mapping), and [data_sync](../../app/routes/admin_sections/data_sync).

The admin panel is accessible to authenticated users with the appropriate role. Some panels are admin-only; others are accessible to project PIs for their own project scope.

CLI commands and initialization services remain available for initial bootstrap and bulk operations, but day-to-day operational setup is now self-service through the web UI.

## Admin Panel Overview

The `/admin` interface provides the following management panels:

- **Access Grants** — manage user-to-project/site role assignments
- **Project Sites** — manage which sites are associated with a project
- **Project Forms** — per-site ODK form mapping (ODK project ID and xmlFormId), with live dropdowns populated from ODK Central via pyODK
- **Project PIs** — manage PI assignments scoped to a project
- **Projects** — project master management (create, activate, deactivate)
- **Sites** — site master management (create, activate, deactivate)
- **Users** — user account management (create, reset password, toggle active status, assign coder languages)
- **ODK Connections** — CRUD for ODK Central connections, encrypted credential storage, test connection, and project assignment
- **Languages** — canonical language list management with ODK alias mapping. Shows unmapped language values found in submissions.
- **COD Buckets** — admin editor for imported COD reporting schemes, including hierarchy labels/order and single-target ICD-to-disease remapping by age scope.
- **ICD-10 Browser** — admin browser for `mas_icd10_2019_2`, including lazy hierarchy traversal, local policy-field curation, and JSON export of curated code-policy rows.

All state-changing routes in the admin panel enforce CSRF protection via the `X-CSRFToken` request header.

The sync dashboard also includes ODK-backed backfill tooling:

- a project/site/form coverage table that shows ODK data, local data, metadata, and attachment completeness
- a per-form `Backfill` trigger that repairs only missing thin rows and local metadata, attachment, or SmartVA gaps for that form
- a separate per-form `Force-resync` trigger that performs a full redownload for the selected form
- a separate attachment-cache backfill trigger that only repairs missing local attachment files for already stored submissions
- a dedicated legacy-attachment panel that reports `va_submission_attachments`
  rows where `storage_name IS NULL`, split between `audit.csv` rows and actual
  media rows, plus a derived count of already repaired legacy media rows
- a legacy-attachment `Repair` trigger that populates deterministic
  `storage_name` values for legacy non-`audit.csv` media rows and renames the
  local files to their opaque storage tokens

### Admin-Only Panels

The following panels are restricted to application-level admins:

- ODK Connections
- Users
- Sites
- Projects
- Languages
- COD Buckets
- ICD-10 Browser

### Project-PI-Accessible Panels

Project PIs can access the following panels, scoped to their own project:

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
- Social Autopsy analysis enablement
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
- the same Configure row also edits the materialized compatibility `va_forms`
  SmartVA execution settings for that project/site form:
  - HIV
  - malaria
  - HCE
  - freetext
  - country
- saving a mapping now ensures the runtime `va_forms` row exists immediately,
  so SmartVA settings can be persisted before the first sync run
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
- deactivated languages are hidden from admin user-language assignment but existing data is preserved

## Users Panel And Language Assignment

The Users panel is the operational place to manage each user's `vacode_language`
selection.

Current behavior:

- admins assign one or more active canonical languages when creating a user
- admins can later edit that language set for existing users
- those assigned languages drive coder and reviewer narration-language filters
- the self-service My Profile page no longer edits coding languages; it only
  handles password and timezone changes

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

Operational setup now uses Flask CLI commands registered by the application
factory instead of legacy shell-context helpers in [`run.py`](../../run.py).
The shell context is intentionally minimal and exposes only `db` and
`sqlalchemy` as `sa` for inspection/debugging.

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

Fresh initialization is additive and command-driven. The standard baseline is
`flask seed run`, which creates the default admin user, canonical languages,
the `WHO_2022_VA` form type, and field/choice mappings without test data.

## Mapping Administration

Mapping spreadsheets are stored under:

- `resource/mapping`

The app does not read them dynamically from the UI on every request. The
runtime field-mapping tables are populated by the seed/migration command path,
while the remaining static compatibility mappings live under
`app/services/forms/legacy_mappings`. Active helper code imports concrete
domain modules directly; `app/utils` is no longer a re-export barrel and now
contains only generic non-domain helpers.

## Validators And Helper Boundaries

Domain validators used by setup/admin services live under
[`app/validators`](../../app/validators):

- `forms.py` validates form identifiers, ODK form uniqueness/connectivity,
  SmartVA boolean flags, and SmartVA countries.
- `projects.py` validates project identifiers, site identifiers, and project
  display codes.

Service and route helpers should import validators from these modules directly
instead of from the old legacy utility tree. User setup validators now live in
`app/validators/users.py`.

## User And Access Administration

The admin UI supports:

- creating and deactivating user accounts
- resetting user passwords
- assigning and revoking user access grants scoped to projects and sites

Underlying legacy seed helpers remain available for bootstrap operations:

- `va_user_create`
- `va_form_addform`
- `va_site_addsite` from `app/services/projects/sites.py`
- `va_researchproject_addproject` from `app/services/projects/research_projects.py`

## Operational Consequences

The admin UI makes the platform self-service for:

- adding and managing users
- assigning access grants
- configuring ODK connections and project-site form mappings
- managing project and site master records

Mapping spreadsheet regeneration and full platform initialization remain developer/operator tasks performed through the Flask shell.
