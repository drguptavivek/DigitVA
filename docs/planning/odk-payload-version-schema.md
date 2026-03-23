---
title: ODK Payload Version Schema Draft
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-03-23
---

# ODK Payload Version Schema Draft

## Purpose

This draft defines the first schema shape for making ODK sync explicitly
payload-version-aware before SmartVA run-history expansion.

The design goal is to preserve lineage between:

- the active `va_submissions` row
- superseded ODK payloads
- pending upstream payloads detected on protected finalized submissions
- future SmartVA runs
- future coder and reviewer final-COD artifacts

## Design Principles

- additive migration only
- no destructive rewrite of `va_submissions`
- `va_submissions` remains the active submission summary row during cutover
- payload-version history becomes the canonical lineage layer
- protected-state upstream changes must not silently replace the active payload

## Proposed Table

### `va_submission_payload_versions`

One row per normalized ODK payload version for a `va_sid`.

Suggested columns:

| Column | Type | Notes |
|---|---|---|
| `payload_version_id` | UUID PK | stable internal key |
| `va_sid` | FK -> `va_submissions.va_sid` | source submission |
| `source_updated_at` | timestamptz | normalized ODK updated timestamp |
| `payload_fingerprint` | text | canonical normalized hash/fingerprint |
| `payload_data` | JSONB | full normalized ODK payload snapshot |
| `version_status` | text / enum | `active`, `pending_upstream`, `superseded`, `rejected` |
| `created_by_role` | text | normally `vasystem` |
| `created_by` | UUID nullable | actor id when human-created transition exists |
| `version_created_at` | timestamptz | creation timestamp |
| `version_activated_at` | timestamptz nullable | set when version becomes active |
| `superseded_at` | timestamptz nullable | set when replaced |
| `rejected_at` | timestamptz nullable | set when pending upstream version is rejected |
| `rejected_reason` | text nullable | optional human reason |

Recommended indexes:

- unique partial index on one active version per `va_sid`
- index on `(va_sid, version_status)`
- index on `(va_sid, payload_fingerprint)`
- index on `source_updated_at`

## Recommended Companion Changes

### `va_submissions`

Keep as the active summary row for now.

Add candidate column:

| Column | Type | Notes |
|---|---|---|
| `active_payload_version_id` | UUID nullable FK | points to the currently active payload version |

Reason:

- fast current-state lookup
- explicit linkage from live submission row to current active payload version

### `va_submission_upstream_changes`

Keep during cutover, but reposition it as the protected-state decision record
rather than the long-term payload-history store.

Future relationship:

- `previous_payload_version_id`
- `incoming_payload_version_id`

This allows the table to remain the accept/reject workflow artifact while
payload history moves into `va_submission_payload_versions`.

## Version State Semantics

### `active`

- current accepted source payload
- basis for workflow, SmartVA, coder COD, reviewer COD

### `pending_upstream`

- changed payload detected while current workflow state is protected/finalized
- not yet accepted into the active path
- should not trigger SmartVA automatically

### `superseded`

- previously active payload replaced by a newer accepted version

### `rejected`

- pending upstream payload was reviewed and rejected
- kept for audit/history, but never became active

## Sync Write Rules

### First sync

- create `va_submissions`
- create payload version with status `active`
- set `va_submissions.active_payload_version_id`

### Unchanged sync

- no new payload version
- do not reroute workflow solely due to ODK timestamp drift

### Changed sync, non-protected state

- create new payload version with status `active`
- supersede prior active payload version
- update `va_submissions.active_payload_version_id`
- route to `smartva_pending`

### Changed sync, protected finalized state

- create new payload version with status `pending_upstream`
- do not replace current active payload version
- create/update `va_submission_upstream_changes`
- route to `finalized_upstream_changed`

## Accept / Reject Rules

### Accept upstream change

- promote pending version to `active`
- supersede previous active version
- update `va_submissions.active_payload_version_id`
- route to `smartva_pending`

### Reject upstream change

- mark pending version as `rejected`
- keep current active version unchanged
- return workflow to prior finalized path

## Future Linkage Targets

These are not part of the first schema migration, but this table is being
designed to support them:

- `va_smartva_results.payload_version_id`
- `va_final_assessments.payload_version_id`
- `va_reviewer_final_assessments.payload_version_id`
- `va_final_cod_authority` resolving within active payload-version lineage

## Migration Strategy

### Phase A

- create `va_submission_payload_versions`
- add `va_submissions.active_payload_version_id`
- no runtime cutover yet

Current status:

- implemented

### Phase B

- backfill one active payload version from each current `va_submissions.va_data`
  row
- backfill `active_payload_version_id`

Current status:

- implemented via Alembic data migration
- live app DB verification after migration:
  - `va_submission_payload_versions`: 7941 rows
  - `va_submissions` missing `active_payload_version_id`: 0

### Phase C

- cut sync write path to create/update payload-version rows
- keep `va_submissions.va_data` updated for compatibility

Current status:

- implemented
- runtime now:
  - creates one active payload version on first sync
  - leaves payload-version rows unchanged for unchanged syncs
  - creates a new active payload version for changed non-protected syncs
  - creates a pending upstream payload version for changed protected finalized
    syncs
- focused verification:
  - `tests/services/test_odk_sync_service.py`
  - `tests/services/test_odk_sync_workflow_guards.py`
  - `19 passed`

### Phase D

- cut upstream accept/reject flow to promote/reject payload versions

Current status:

- implemented
- accept now:
  - promotes the pending upstream payload version to `active`
  - supersedes the prior active payload version
  - updates `va_submissions.active_payload_version_id`
  - projects the accepted payload onto the active summary row
- reject now:
  - marks the pending upstream payload version `rejected`
  - preserves the current active payload version
  - restores the prior finalized workflow state from the upstream-change record
- focused verification:
  - `tests/services/test_data_management_service.py`
  - `21 passed`

### Phase E

- bind SmartVA artifacts to payload-version ids

Current status:

- implemented
- `va_smartva_results.payload_version_id` now exists
- existing SmartVA rows were backfilled from
  `va_submissions.active_payload_version_id`
- SmartVA run history is now stored separately in:
  - `va_smartva_runs`
  - `va_smartva_run_outputs`
- `va_smartva_results` now points to the originating run via `smartva_run_id`
- SmartVA readiness and active-result checks now operate against the current
  active payload version
- focused verification:
  - `tests/services/test_smartva_service.py`
  - `18 passed`

### Phase F

- bind human final-COD artifacts to payload-version ids
- resolve final COD authority within active payload lineage

Current status:

- implemented
- `va_final_assessments.payload_version_id` now exists
- `va_reviewer_final_assessments.payload_version_id` now exists
- existing coder/reviewer final-COD rows were backfilled from
  `va_submissions.active_payload_version_id`
- authority resolution ignores stale coder/reviewer final-COD rows from
  superseded payload versions

## Resolved Decisions

- `version_status` will use constrained text, not a PostgreSQL enum
- `payload_fingerprint` will be the hash of full canonical normalized JSON
- `payload_data` will store the full normalized ODK payload
- rejected upstream payload versions will be kept indefinitely for audit
- every existing `va_submissions` row should receive one initial active payload
  version during backfill
- `va_submissions.va_data` remains the active summary payload during transition
- changed non-protected payloads should route to `smartva_pending`
- changed protected finalized payloads should route to
  `finalized_upstream_changed`

Protected finalized states for this routing rule are:

- `coder_finalized`
- `reviewer_eligible`
- `reviewer_finalized`
- `finalized_upstream_changed`
- legacy `closed` if such rows exist
