# Health-system organization model

- Status: phases 1–2 done (2026-09-17); phases 3–5 pending
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

Phases 3–5 in the plan (routing by `org_<level>_code` and multiple ODK forms
per project, coding-scope enforcement, reporting dimensions). Additive
migrations only.

## Done

- Phase 1 (`c8d2e4f6a1b3`): levels, units with ltree paths, cadres, level ×
  cadre permissions, workers, admin Organization panel, export/import, ODK
  choices export, `flask org` CLI.
- Phase 2 (`d9e3f5a7b2c4`): `org_unit` grant scope covering a unit subtree,
  descriptive `cadre_id` validated against the level × cadre grid (a coder
  grant needs a cadre that may code there), resolution in
  `app/services/org_grant_service.py`, unit/cadre pickers and a unit-grants
  table in the Access Grants panel, unit scope refused on the data-manager
  grant endpoints. Coding and review surfaces still resolve through
  `va_forms`; enforcement is phase 4.

## Next

Phase 3: `map_project_site_odk` gains `org_unit_id`, uniqueness moves to
(project, site, odk_project_id, odk_form_id) so one DigitVA project accepts
several ODK forms over one connection, `va_submissions.org_unit_id` is routed
from the `org_<level_code>_code` payload fields with a data-manager unrouted
queue for the fallbacks.
