# Demo Retention Leaves Step 1 COD Stuck

Status: fixed locally, pending deployment/cleanup run
Priority: high
Created: 2026-05-20

## Goal

Ensure demo/training submissions return to `ready_for_coding` after demo
retention expires.

## Context

`SADEMO / DEMO` form `SADEMODEMO01` had 24 submissions, but demo coding showed
"No forms are currently available for demo coding."

Database state showed:

- 22 submissions in `coder_step1_saved`
- 1 submission in `consent_refused`
- 1 submission in `not_codeable_by_coder`
- 0 submissions in `ready_for_coding`

The 22 stuck rows were coded between 2026-04-29 and 2026-05-01 UTC. Demo final
COD rows expired correctly, but matching active Step 1 COD rows remained in
`va_initial_assessments`, so workflow inference restored `coder_step1_saved`
instead of `ready_for_coding`.

## Fix

Patch `cleanup_expired_demo_coding_artifacts()` so demo retention cleanup:

- deactivates the matching active Step 1 COD row for the user whose expired
  demo final COD is being cleaned
- audits that deactivation as `initial cod expired after demo retention`
- repairs already-stuck rows where the demo final is already deactivated and
  expired but Step 1 remains active

## References

- `app/services/coding_allocation_service.py`
- `tests/services/test_coding_allocation_service.py`
- `docs/policy/demo-coding-retention.md`
- `docs/policy/coding-workflow-state-machine.md`
- `docs/current-state/workflow-and-permissions.md`

## Verification

Passed:

- `docker compose exec minerva_app_service uv run pytest tests/services/test_coding_allocation_service.py`
- `docker compose exec minerva_app_service uv run pytest tests/routes/test_demo_final_cod.py`
- `docker compose exec minerva_app_service uv run pytest tests/routes/test_demo_random_coding.py`
- `git diff --check`

## Follow-Up

- Deploy/restart app, worker, and beat so Celery imports the patched cleanup
  code.
- Confirm the next 15-minute demo cleanup run repairs the 22
  `SADEMODEMO01` rows and returns them to the demo pool.
