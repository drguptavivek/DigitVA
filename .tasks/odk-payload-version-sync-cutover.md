Status: complete
Priority: high
Created: 2026-03-23
Goal: Introduce and roll out a payload-version-aware ODK sync and SmartVA lineage model.

Context:

- Current policy now defines `payload version`, `active payload version`, and
  `pending upstream payload version` in
  [`docs/policy/odk-sync-policy.md`](../docs/policy/odk-sync-policy.md).
- Current runtime now uses payload-version-aware sync, upstream-change
  promotion, SmartVA linkage, and coder/reviewer final-COD linkage.
- Remaining work is mainly rollout/backfill completion and any remaining reader
  cleanup that still assumes pre-redesign SmartVA storage details.

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
5. Keep SmartVA and human-coding artifacts bound to payload-version ids and
   complete rollout/backfill for existing live data.

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
   Current status: implemented with:
   - `va_smartva_form_runs` for form-level execution metadata
   - `va_smartva_runs.form_run_id` linkage
   - on-disk raw SmartVA outputs under `APP_DATA`
   - `va_smartva_run_outputs` for likelihood rows only
   - `va_smartva_results` as the active projection
8. Human coding artifact linkage
   Current status: implemented for coder final, reviewer final, and
   final-COD-authority lineage checks.
9. Later phases: reader/reporting parity and project-by-project backfill

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
- Phase E SmartVA payload-version linkage: implemented and verified
- SmartVA form-run redesign: implemented
- `va_smartva_prepdata` DB payload cutover: implemented
- `va_smartva_run_artifacts` retirement in active runtime path: implemented
- Phase F human coding artifact linkage: implemented and verified with focused
  tests
- `report.txt` SmartVA rejection parsing: implemented and verified
- Scoped backfill completed for:
  - `UNSW01`
  - `ICMR01`
- Reader/reporting parity audit (2026-03-24): all routes, services, utilities,
  and templates confirmed on new semantics. No legacy artifact reads found.
  Old artifact table already dropped in migration 5e6f7a8b9c0d.
  Track 2 complete — no code changes needed.

- Backfill complete: global `candidate submissions: 0`, `candidate forms: 0`
  (as of 2026-03-23). All projects processed: UNSW01, ICMR01, ZZZ99 (test
  fixture — outcome=failed as expected).
- Backfill script updated to treat `outcome=failed` + non-null `disk_path`
  as a terminal state (skip from candidates).
