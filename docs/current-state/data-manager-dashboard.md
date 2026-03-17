---
title: Data Manager Dashboard
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-18
---

# Data Manager Dashboard

## Purpose

The data-manager dashboard provides scope-based operational visibility into ODK
submissions before coder allocation.

Route:

- `/vadashboard/data_manager`

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

## Summary Cards

Current cards include:

- `Submissions`
- `Flagged Not Codeable`
- `ODK - Has Issues`
- `SmartVA Missing`

Some card counts apply filters directly to the table when clicked.

## Submission Table

The table currently shows scoped submissions with:

- masked ID
- project/site
- submitted date
- workflow state
- ODK review state
- ODK sync issue state
- SmartVA availability
- attachment count
- optional columns such as project, collector, and flagged-at timestamp

The table also includes an `Edit` action that resolves a server-side ODK Central
submission edit redirect and sends the user to the returned Enketo edit URL.

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

## Charts

The dashboard includes a compact project-site submissions chart rendered with a
local vendored copy of Chart.js.

Current chart API:

- `/vadashboard/data-manager/api/project-site-submissions`

This chart currently uses a route-level scoped query. It has not yet been
migrated to the submission analytics materialized view.

## Recent Sync Results

The dashboard includes a collapsed-by-default recent sync results panel.

It shows recent data-manager initiated sync runs with:

- start time in the user timezone
- run status
- records added/updated
- latest progress/error entries

## Related Files

Main route and query logic:

- [va_main.py](../../app/routes/va_main.py)

Template and client-side behavior:

- [va_data_manager.html](../../app/templates/va_frontpages/va_data_manager.html)

Background sync tasks:

- [sync_tasks.py](../../app/tasks/sync_tasks.py)
