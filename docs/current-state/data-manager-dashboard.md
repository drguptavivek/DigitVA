---
title: Data Manager Dashboard
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-06
---

# Data Manager Dashboard

## Purpose

The data-manager dashboard provides scope-based operational visibility into ODK
submissions before coder allocation.

Route:

- `/data-management`

## Access Model

Dashboard visibility is grant-scoped.

Supported scope behavior:

- project grants see all submissions/forms in the project
- project-site grants see only that project/site pair

The dashboard and sync actions both enforce scope derived from current user grants.

## What The Dashboard Shows

Current dashboard sections include:

- summary KPI cards
- project-site submission chart
- sync action modal and preview
- recent sync results
- browse/search filters
- submission table with ODK, workflow, SmartVA, and attachment visibility
- export dropdown for filtered CSV exports

## Summary Cards

Current cards include:

- `Submissions`
- `Pending Coding`
- `SmartVA Queue`
- `Coded`
- `Flagged Not Codeable`
- `ODK - Has Issues`
- `SmartVA Missing`

Some card counts apply filters directly to the table when clicked.

Current `Pending Coding` semantics:

- `Pending Coding` counts only coder-actionable workflow states:
  - `ready_for_coding`
  - `coding_in_progress`
  - `coder_step1_saved`
- pre-coding pipeline states such as:
  - `screening_pending`
  - `attachment_sync_pending`
  - `smartva_pending`
  are not counted as pending coding

## Submission Table

The dashboard shell does not preload the submission table server-side.

Current load path:

- the HTML route renders KPI cards, chart containers, filters, and grid shell
- the top-level dashboard template is now a thin shell that composes partials for the page header, KPI cards, charts, table shell, offcanvas panels, sync modal, and workflow guide
- dashboard-specific styles are served from a cacheable static CSS file instead of a large inline `<style>` block
- the main dashboard bootstrap code is served from `static/js/data_manager_dashboard.js` instead of a large inline `<script>` block
- the Mermaid workflow guide is served from `static/js/data_manager_workflow_guide.js` and only loads Mermaid when the guide is opened
- the table rows load lazily through the paginated API
- AG Grid uses the infinite row model and fetches rows from `/api/v1/data-management/submissions`
- the submissions API avoids a full `COUNT(*)` on each page request by over-fetching one row to detect the end of the result set
- the page opts out of the shared DataTables, jQuery, Select2, Cropper, and HTMX assets from the VA base template
- Chart.js is loaded only when deferred chart rendering begins
- KPI counts load immediately after the shell is ready
- filter option hydration runs separately and does not block the initial table shell
- non-critical charts are deferred until after the first paint / idle window

The table currently shows scoped submissions with:

- masked ID
- project/site
- submitted date
- workflow state
- coded-on / coded-by for coded submissions
- ODK review state
- ODK sync issue state
- SmartVA availability
- attachment count
- optional columns such as project, collector, and flagged-at timestamp

The table also includes an `Edit` action that resolves a server-side ODK Central
submission edit redirect and sends the user to the returned Enketo edit URL.

For `finalized_upstream_changed` rows, the current actions also include:

- `View Changes`, which opens a modal backed by the normalized upstream-change
  details API

The modal now presents:

- `Data Changes`
- `Metadata Changes`
- `Formatting-Only Changes`

Current action placement:

- AG Grid shows `View` and `View Changes`
- `Accept And Recode` and `Keep Current ICD Decision` are modal-only actions
- the data-manager detail page also uses a modal-only `View Changes` flow

Current action semantics:

- `Accept And Recode` uses the new ODK data, clears old assigned ICD codes, and returns
  the form for recoding
- `Keep Current ICD Decision` adopts the latest ODK payload locally while
  preserving the current finalized ICD Code decision and finalized workflow
  state

Both actions now open a second confirmation modal before execution.

## Filters

Current filter behavior includes:

- project
- site
- submitted from/to
- ODK status
- SmartVA
- ODK sync
- workflow state
- free-text search
- optional column toggles

Filter state persists across page reloads in the browser.

## Exports

The dashboard header includes an `Export` dropdown.

Current export actions:

- `Export Data`
- `SmartVA Input Data`
- `Results`
- `Likelihoods`

Current export behavior:

- all exports reuse the current dashboard filters and sort order
- CSV responses are emitted as UTF-8 with BOM for Excel compatibility
- `Export Data` includes current workflow/coding state and the filtered ODK
  payload data
- `SmartVA Input Data` exports the cleaned SmartVA preparation input shape for
  the active payload
- `Results` exports active SmartVA summary result fields only
- `Likelihoods` exports raw active SmartVA likelihood rows only

Current PII handling:

- exports omit payload fields marked `is_pii=true` in field mapping
- exports also omit selected local identifier columns such as
  `va_uniqueid_real`, `va_instance_name`, and `va_data_collector`
- the main data export retains non-PII narrative text such as `Id10476`
- SmartVA exports do not include the full raw `va_data` payload

## Sync UX

The dashboard supports scoped sync initiation through a modal.

Current sync behavior:

- project/site scope selection inside the modal
- explicit matched-form confirmation
- live preview of local versus ODK counts
- warning that missing ODK records are flagged locally, not deleted
- background task dispatch through Celery

Supported actions:

- per-form sync
- per-submission refresh

Single-submission refresh also refreshes attachments and SmartVA for that submission.

## ODK Visibility

The dashboard mirrors key ODK metadata locally so data managers do not need to
use ODK Central for routine triage.

Current locally exposed items include:

- ODK review state
- ODK review comments
- local sync-issue markers such as `missing_in_odk`
- locally tracked attachment counts
- normalized changed-field details for pending protected upstream updates via:
  - `/api/v1/data-management/submissions/<va_sid>/upstream-change-details`
  - data-manager detail-page modal `View Changes`
  - dashboard modal `View Changes`

## Charts

The dashboard includes a compact project-site submissions chart rendered with a
local vendored copy of Chart.js.

Current chart API:

- `/data-management/api/project-site-submissions`

This chart currently uses a route-level scoped query. It has not yet been
migrated to the submission analytics materialized view.

The workflow distribution donut and workflow guide both show actual local
workflow states, including pre-coding pipeline states such as:

- `screening_pending`
- `attachment_sync_pending`
- `smartva_pending`
- `ready_for_coding`

Clicking a segment filters the dashboard table to that exact workflow state.

## Recent Sync Results

The dashboard includes a collapsed-by-default recent sync results panel.

It shows recent data-manager initiated sync runs with:

- start time in the user timezone
- run status
- records added/updated
- latest progress/error entries

## User and Grant Management

The data-manager dashboard includes a "Manage Users" button in the page header
that links to `/data-management/users`.

This page provides a separate interface (outside the admin panel) where
data-managers and admins can:

- **Users tab**: search active users and create new users (with email, name,
  phone, password, and VA language selection)
- **Grants tab**: view, create, and toggle coder and data-manager grants
  scoped to the data-manager's own grant scope

Scope rules:

- project-scoped data-managers can assign grants at project or project-site
  level within their project
- site-scoped data-managers can only assign grants at project-site level for
  their specific sites
- admins bypass all scope restrictions through this interface

Assignable roles are limited to `coder` and `data_manager`. The interface does
not expose admin, project-PI, site-PI, reviewer, or collaborator grants.

See [dm-user-grant-management.md](../../docs/policy/dm-user-grant-management.md)
for the full policy baseline.

## Related Files

Main route and query logic:

- [data_management.py](../../app/routes/data_management.py)

Template and client-side behavior:

- [va_data_manager.html](../../app/templates/va_frontpages/va_data_manager.html)
- [data_manager_partials](../../app/templates/va_frontpages/data_manager_partials)
- [_user_management.html](../../app/templates/va_frontpages/data_manager_partials/_user_management.html)
- [data_manager_dashboard.js](../../app/static/js/data_manager_dashboard.js)
- [data_manager_workflow_guide.js](../../app/static/js/data_manager_workflow_guide.js)
- [data_manager_dashboard.css](../../app/static/css/data_manager_dashboard.css)

Background sync tasks:

- [sync_tasks.py](../../app/tasks/sync_tasks.py)
