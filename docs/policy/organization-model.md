---
title: Organization Model Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-18
---

# Organization Model Policy

## Purpose

Health-system deployments organize VA work along the public health hierarchy
(District > Taluka > CHC > PHC > Sub-centre > Village), not along research
sites. This policy defines how a project describes that hierarchy, who sits
where in it, and what the codes mean for ODK forms, coding scope and
reporting. Planning context:
`docs/planning/health-system-organization-model-plan.md`.

## In plain terms

This section orients a reader who is not implementing the code. The rules that
govern behaviour are the ones below it; where the two ever disagree, the rules
below win.

Nobody in DigitVA simply *has* permissions. Permission is handed out one record
at a time, and each record says three things: **who** (a person with a login),
**what job** (the role: coder, reviewer, data manager, site PI, project PI,
admin), and **where** (the scope — the boundary that job applies inside).

The system never infers. If no record says a person may do something, they may
not. Access is not inherited from a job title, from seniority, from being
someone's supervisor, or from a field being left blank. A data manager who
should also code needs a second record saying so.

The "where" used to be a research shape — Project > Site > Form — which suits a
study with a handful of field sites. A health system is a tree instead:

```
District
 └─ CHC            community health centre
     └─ PHC        primary health centre
         └─ Sub-centre
             └─ Village
```

A project now describes its own tree, and a permission record may point at any
node of it. **Pointing at a node means that node and everything beneath it.**
Point at the CHC and the person covers that CHC, its PHCs, their sub-centres
and villages. Point at one PHC and they cover that branch only — not the CHC
above, not the neighbouring PHC.

A **cadre** is the health-system job title: SMO, MO, CHO, ANM, ASHA. Each
project fills in a grid saying which cadres exist at each level of its tree and
what they may do there — at a PHC an MO may code a death while a CHO may fill
the form but not code it.

The cadre is **not itself a permission**. It is a check made when the
permission record is written. Think of a keycard: the role is what kind of card
it is, the scope is which doors it opens, and the cadre is the job title
printed on the front. Whoever issues the card refuses to print "coder" for
someone whose title may not code at that location — but once the card exists,
the door reads the card, never the printed title. So a coder record at a PHC is
refused for a CHO and accepted for an MO; afterwards the cadre stands as a
record of who the person is.

Incoming submissions are attributed to a unit automatically: the form carries
the unit codes, and DigitVA reads the most specific one the interviewer
answered. Where that fails, the submission waits in a data manager's queue to
be assigned by hand.

One caveat worth stating plainly: the coding screens do not consult any of
this yet. What a coder can actually open is still resolved the old way,
through forms and sites, so a unit-scoped permission record and a submission's
routed unit are both correctly stored facts that do not yet change anyone's
working day. Enforcement is the next phase. See
[Not yet implemented](#not-yet-implemented-later-phases-of-the-plan).

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
  a runtime authorization path. Runtime access comes from explicit
  user × role × scope grants (see
  [Access Control Model](access-control-model.md)).

## Unit-scoped grants

- A grant may carry `scope_type = 'org_unit'` with an `org_unit_id`. The grant
  covers that unit **and its whole subtree**, resolved through the unit's
  ltree path.
- Roles accepted at unit scope: `site_pi` (oversight of a subtree),
  `collaborator`, `coder`, `coding_tester`, `reviewer`, `data_manager`.
  `admin` stays global and `project_pi` stays project-scoped.
- A unit grant carries no `project_id` or `project_site_id`. The grant's
  project is the unit's project, and every project filter resolves it that way.
- The `cadre_id` on a grant is **descriptive**: it records which cadre the
  person holds at that unit, and nothing at runtime consults it. It is
  validated when the grant is written:
  - the cadre must belong to the unit's project and be active;
  - the cadre must be defined at the unit's level in the level × cadre grid;
  - a `coder` grant **must** name a cadre, and that cadre must have
    `can_code_va_form` at that level.
- A cadre may only be set on a unit-scoped grant (database constraint).
- One active grant per user × role × unit (partial unique index).
- Deactivating a unit removes it, and everything beneath it, from every
  grant's resolved scope without touching the grant rows. Reactivating the
  unit restores them.
- Unit-scoped grants are created from the **admin user panel**, which carries
  the unit and cadre pickers. The data-manager grant interface knows only
  projects and sites and refuses to create or revoke a unit grant, for admins
  too; a data manager still *sees* the unit grants of their own project in the
  grant list, as they already see its project and site grants.
- `flask users grant` does not create unit grants; use the admin panel or the
  `/admin/api/access-grants` endpoint.
- Every unit grant mutation is written to `grants.log` with the unit and cadre.

## Submission routing

- A project's ODK form carries one field per level, named
  `org_<level_code>_code`, filled from the unit codes DigitVA exports. Routing
  reads those fields and takes the **deepest** one that names a live unit of
  that project at that level.
- A code that names no live unit, or that names a unit at a different level
  than the field it arrived in, is not trusted: routing keeps looking up the
  tree and logs the mismatch.
- Codes are matched case-insensitively, and are read whether ODK delivers the
  field bare (`org_phc_code`) or inside a group path (`.../org_phc_code`).
- When nothing in the payload resolves, the submission falls back to the unit
  named on its ODK form mapping (`map_project_site_odk.org_unit_id`) — for a
  project whose single Central form serves many interviewers, typically a
  district or the project root. An inactive fallback, or one belonging to
  another project, is ignored.
- When there is no fallback either, the submission stays **unrouted** and
  appears in the data manager's unrouted queue.
- `va_submissions.org_unit_resolution` records how the unit was decided:
  `form_field`, `mapping_fallback` or `manual`.
- Routing is **idempotent**: the same payload always yields the same unit, so
  re-running a sync rewrites nothing. A payload change re-routes the
  submission, so a corrected form moves the death to the right unit.
- A **manual pin** by a data manager sets `manual` and is never overwritten by
  a later sync. Clearing the pin hands the submission back to routing.
- A project with no organization tree is left alone entirely: its submissions
  stay unrouted, which is what unrouted means for it.
- Web-intake submissions route by the same rules, since the web questionnaire
  carries the same fields and the project-site's ODK mapping supplies the same
  fallback.
- Deactivating a unit does not rewrite the submissions already attributed to
  it; the next sync of an affected submission re-routes it.

## Not yet implemented (later phases of the plan)

- several ODK forms per project-site: `map_project_site_odk` is still unique on
  (project, site), so one DigitVA project-site holds one ODK form
- project coding-scope level and above-scope mode; until then a unit grant
  does not change what a coder may open — coding eligibility still resolves
  through `va_forms`, and a submission's routed unit is recorded but not
  enforced
- unit dimensions in dashboards, exports and analytics
