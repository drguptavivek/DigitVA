# Health-system organization model

- Status: phases 1–4 done (2026-09-18); phase 5 pending
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

- Phase 3a (`c1d4e7f9a3b6`): submissions routed to units from the
  `org_<level_code>_code` payload fields, with a mapping fallback unit, a
  data-manager unrouted queue, and the ODK form-field contract shown in the
  Organization panel plus a live preflight check against the mapped form.
- Phase 3b (`e2a5c8b1d7f3`): several ODK forms per project-site; each mapping
  materializes its own `va_forms` row, matched on the ODK ids.

- Phase 4 (`f7b2d4e6a8c9`): project coding scope level and above-scope mode,
  the eligibility rule in `org_grant_service.codeable_unit_ids`, the shared
  list filter in `coder_workflow_service._org_unit_scope_filter`, and the
  per-submission gate in `va_validate_permissions` for the coder and reviewer
  tracks. Projects without an organization tree are unaffected.

## Next

Phase 5: unit dimensions in dashboards, exports and analytics — unit path in
the analytics MV, unit as a grouping dimension in DM KPIs, and
`org_unit_code` / `org_unit_name` / level path columns in the exports.
