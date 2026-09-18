# Per-unit coding gates

- Status: pending
- Priority: medium
- Created: 2026-09-18

## Goal

Express the coding gates per organization unit, not only per project-site: a
coding window, an enabled flag and a daily coder limit for one PHC rather than
for the whole site.

## Decision (2026-09-18)

Yes — health-system projects want these per unit. Today they exist only on
`va_project_sites` (`coding_enabled`, `coding_start_date`, `coding_end_date`,
`daily_coder_limit`), which for a tree project is one container row covering
every unit beneath it.

## Context

Organization model phases 1-4
(`docs/current-state/health-system-organization-model.md`). The site gates are
applied in `app/services/coder_workflow_service.py::_get_excluded_sites_for_coding`,
which also carries the coding_tester and PI waivers. Unit scope resolution
lives in `app/services/org_grant_service.py::codeable_unit_ids`.

## Expected Scope

- somewhere to hold the gates per unit. Either columns on `mas_org_unit` or a
  `map_org_unit_coding_gate` table; prefer the mapping table if the gates are
  expected to grow, since `mas_org_unit` is already wide
- decide **inheritance**: does a gate on a CHC apply to the PHCs beneath it,
  or only to deaths routed to the CHC itself? The subtree reading is the more
  useful one and matches how grants work, but it means resolving the nearest
  ancestor that sets a gate
- decide **precedence** against the existing site gate: the stricter of the
  two, or the unit gate overriding the site gate where set
- the daily limit is per coder per unit and must not be double-counted against
  the site limit
- keep the coding_tester and PI waivers behaving as they do for sites
- admin UI on the Organization panel's unit editor
- tests: a closed unit excluded while its siblings stay open; inheritance in
  whichever direction is chosen; the daily limit counted once; waivers intact

## Risks

Touches the allocation path that every coder uses. The site gates and the unit
gates must compose predictably, or a coder is silently blocked with no
explanation on screen.
