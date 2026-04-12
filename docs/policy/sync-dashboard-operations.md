---
title: Sync Dashboard Operations Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-12
---

# Sync Dashboard Operations Policy

## Scope

This policy defines operator-facing behavior for the admin sync dashboard at
`/admin/panels/sync`.

## Coverage Loading

ODK coverage counts are operationally expensive because they require live calls
to ODK Central for every active mapping.

Policy:

- the dashboard must not fetch ODK coverage automatically on initial panel load
- ODK coverage must be loaded only when the operator explicitly requests it
- the UI must make it clear that coverage is on-demand
- local-only dashboard sections (status, repair coverage) may still load
  automatically because they do not require the same live ODK count fan-out

## Connection Health Visibility

Operators need to see when live ODK actions are likely to fail before they
start expensive or repeated requests.

Policy:

- the sync dashboard status area must surface active ODK connection cooldowns
  and recent retryable connection failures
- these alerts are informational and must not trigger additional live ODK calls
- the alerts should help explain why coverage loads, per-form syncs, or other
  live ODK actions may currently fail fast

## Stop Control

The dashboard must provide an operator stop control while a sync task is
running.

Policy:

- the stop control is shown only when a sync run is active
- activating stop sends a revoke request to the running Celery sync task with
  termination enabled
- the corresponding `va_sync_runs` row must be marked `cancelled`
- cancelled runs remain visible in sync history and status views
- the stop control applies to:
  - full ODK sync
  - SmartVA-only sync
  - single-form sync
  - single-submission sync

## Concurrency

The dashboard must continue to prevent starting a second sync while one is
already running.

Policy:

- `Sync` remains disabled while a run is active
- the stop control is the only operator action exposed for an active run

## Coverage Table Sync Actions

Operators use the coverage table to recover local gaps at the project/site
mapping level, including mappings that do not yet have a local compatibility
`va_forms` row.

Policy:

- rows with an existing local `va_forms` row may continue to expose the
  per-form sync action
- rows with an active mapping but no local `va_forms` row must still expose a
  sync action
- that zero-local-form sync action must first materialize the compatibility
  `va_forms` row for the mapped project/site, then trigger the existing
  form `Sync` path
- operators should not be forced to create local submissions manually before a
  first sync can run for a mapped site
