---
title: Organization Model Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-17
---

# Organization Model Policy

## Purpose

Health-system deployments organize VA work along the public health hierarchy
(District > Taluka > CHC > PHC > Sub-centre > Village), not along research
sites. This policy defines how a project describes that hierarchy, who sits
where in it, and what the codes mean for ODK forms, coding scope and
reporting. Planning context:
`docs/planning/health-system-organization-model-plan.md`.

## Baseline

- Every project may define its **own** organization tree. Projects without a
  tree keep today's Project > Site > Form behaviour unchanged.
- A tree has ordered **levels** (`mas_org_level`), each with a `level_code`, a
  `depth` (1 = top) and an `is_optional` flag. Depth is the only hierarchy
  rule.
- A tree has **units** (`mas_org_unit`). A unit belongs to one level and to
  at most one parent unit at a shallower level. Levels strictly between the
  parent's level and the unit's level must all be optional; otherwise the
  parent must be at the next level up.
- A unit carries: code, name, address, phone, latitude/longitude, Google Maps
  URL, remarks, active flag. Address, phone, coordinates, map URL and remarks
  are optional.
- **Cadres** (`mas_cadre`) are defined per project. The level × cadre grid
  (`map_org_level_cadre`) records which cadres exist at a level and whether
  that cadre `can_fill_va_form` and `can_code_va_form`.
- **Workers** (`mas_org_unit_worker`) are people attached to a unit with a
  cadre; they may or may not have a DigitVA login. A worker's cadre must be
  defined at the unit's level.

## Codes

- Unit, cadre and worker codes are unique **within one project only**. The
  same code may exist in another project with a different meaning.
- Codes are stored upper-case and may contain letters, digits and underscore
  (1 to 32 characters). Level codes are lower-case.
- A unit's `path` is the chain of unit codes from the top of the tree
  (`D01.C01.P01`). Renaming or moving a unit rewrites the paths of its whole
  subtree.
- ODK forms carry one field per level, named `org_<level_code>_code`
  (`org_district_code`, `org_chc_code`, `org_phc_code`, ...). The value is the
  unit code. DigitVA exports the matching XLSForm `choices` rows
  (`list_name = org_<level_code>`, `name` = unit code, `label` = unit name,
  `parent_code` = filter column) so form authors never type codes by hand.

## Lifecycle

- Nothing in the organization model is deleted through the application.
  Deactivation is the only removal.
- Deactivating a unit deactivates its whole subtree. Reactivating a unit
  requires an active parent.
- A level cannot be deactivated, nor its depth changed, while units exist at
  that level.
- Seeding the template (District, Taluka optional, CHC, PHC, Sub-centre,
  Village, with SMO/MO/CHO/MPW/ANM/ASHA) is idempotent: existing codes are
  kept.

## Import and export

- Export produces one workbook with sheets `levels`, `units`, `cadres`,
  `level_cadres`, `workers`, or one CSV per sheet, plus the ODK choices CSV.
- Import reads the same layout, matches rows by code, creates or updates,
  and never deletes. Rows absent from a supplied sheet are deactivated only
  when the operator sets `deactivate_missing`.
- Every import runs as a dry run first. A single invalid row aborts the
  whole import; nothing is written.
- Worker names and phone numbers are personal data: export and import are
  restricted to admins and project PIs of that project and are logged.

## Access

- The Organization panel and its API are available to `admin` and to
  `project_pi` for their own projects.
- Cadre permissions are **metadata that gate grant creation**; they are not
  a runtime authorization path. Runtime access continues to come from
  explicit user × role × scope grants (see
  [Access Control Model](access-control-model.md)). Extending grants with an
  `org_unit` scope is a separate phase.

## Not yet implemented (later phases of the plan)

- `org_unit` scope on access grants and cadre gating of grants
- routing of synced submissions to units from the `org_<level>_code` fields
- project coding-scope level and above-scope mode
- unit dimensions in dashboards, exports and analytics
