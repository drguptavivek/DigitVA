Status: in_progress
Priority: high
Created: 2026-03-23
Goal: Introduce a payload-version-aware ODK sync model before SmartVA run-history expansion.

Context:

- Current policy now defines `payload version`, `active payload version`, and
  `pending upstream payload version` in
  [`docs/policy/odk-sync-policy.md`](../docs/policy/odk-sync-policy.md).
- Current runtime still uses `va_submissions` as the active submission row and
  preserves protected-state lineage through
  [`va_submission_upstream_changes`](../docs/current-state/odk-sync.md), not a
  fully promoted payload-version resolution path.
- SmartVA, coder final COD, and reviewer final COD should eventually bind to a
  payload version, not only to `va_sid`.

References:

- [`docs/policy/odk-sync-policy.md`](../docs/policy/odk-sync-policy.md)
- [`docs/current-state/odk-sync.md`](../docs/current-state/odk-sync.md)
- [`app/services/va_data_sync/va_data_sync_01_odkcentral.py`](../app/services/va_data_sync/va_data_sync_01_odkcentral.py)
- [`app/services/workflow/upstream_changes.py`](../app/services/workflow/upstream_changes.py)
- [`app/services/smartva_service.py`](../app/services/smartva_service.py)
- [`app/services/final_cod_authority_service.py`](../app/services/final_cod_authority_service.py)

Expected Scope:

1. Add additive payload-version persistence for synced ODK payloads.
   Current status: implemented in schema, with backfill migration added.
2. Define canonical changed-vs-unchanged detection using a normalized payload
   fingerprint rather than timestamps alone.
3. Refactor sync so:
   - first sync creates an initial active payload version
   - unchanged syncs do not create a new version
   - changed non-protected syncs create a new active payload version and route
     to `smartva_pending`
   - changed protected syncs create a pending upstream payload version and
     route to `finalized_upstream_changed`
4. Refactor upstream-change accept/reject so:
   - accept promotes the pending payload version to active and routes to
     `smartva_pending`
   - reject preserves the current active payload version
5. Prepare SmartVA and human-coding artifacts to bind to payload-version ids in
   later follow-up phases.

Suggested Delivery Order:

1. Schema draft and migration plan
2. Additive model + migration
3. Backfill one active payload version per existing `va_submissions` row
4. Sync write path cutover
   Current status: implemented for first sync, unchanged detection, changed
   non-protected syncs, and protected changed syncs creating pending upstream
   payload versions.
5. Protected-state accept/reject cutover
   Current status: implemented. Accept promotes the pending payload version to
   active and updates the active summary row. Reject marks the pending payload
   version rejected and restores the prior finalized workflow state.
6. Focused tests for unchanged vs changed payload behavior
7. SmartVA run linkage
   Current status: implemented for `va_smartva_results.payload_version_id`,
   `va_smartva_runs`, `va_smartva_run_outputs`, migration backfill, and
   active-payload-aware readiness checks.
8. Human coding artifact linkage
   Current status: implemented for coder final, reviewer final, and
   final-COD-authority lineage checks.
9. Later phases: reporting updates

Verification Targets:

- unchanged payload sync does not create a new payload version
- changed payload sync creates a new payload version
- protected changed payload creates a pending upstream payload version
- accept upstream change promotes pending to active and routes to
  `smartva_pending`
- reject upstream change leaves current active payload version authoritative

Current progress:

- Phase A schema: implemented
- Phase B backfill: implemented
- Phase C sync write cutover: implemented and verified with focused tests
- Phase D accept/reject promotion: implemented and verified with focused tests
- Phase E SmartVA payload-version linkage: implemented and verified with
  focused tests, including durable run-history persistence
- Phase F human coding artifact linkage: implemented and verified with focused
  tests
