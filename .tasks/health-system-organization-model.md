# Health-system organization model

- Status: phase 1 done (2026-09-17); phases 2–5 pending
- Priority: high
- Created: 2026-09-17

## Goal

Per-project organization tree (District > Taluka > CHC > PHC > Sub-centre >
Village), cadres with fill/code permissions per level, project coding-scope
level with above-scope mode, ODK submission routing to units, master-data
export/import, unit metadata (address, phone, lat/long, map URL, remarks).

## Context

Plan: `docs/planning/health-system-organization-model-plan.md`. Precedes the
ICD-11 coding-screen work for the same deployment
(`.tasks/icd11-coding-screen-integration.md`).

## References

- `app/models/va_user_access_grants.py`
- `app/models/map_project_site_odk.py`, `app/models/va_submissions.py`
- `app/services/coder_workflow_service.py::get_pick_available_forms`
- `app/services/va_data_sync/va_data_sync_01_odkcentral.py`

## Expected Scope

Phases 2–5 in the plan (grants with `org_unit` scope, routing by `org_<level>_code`, coding scope enforcement, reporting); multiple ODK forms per project (phase 3). Additive migrations only.
