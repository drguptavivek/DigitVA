---
title: Health-System Organization Model — Units, Cadres, Coding Scope and Routing
doc_type: planning
status: proposed
owner: engineering
last_updated: 2026-09-18
---

# Health-System Organization Model — Units, Cadres, Coding Scope and Routing

## Requirement (as stated 2026-09-17)

The next deployment is a public health system, not a research site network:

- Community Health Officers (CHOs) fill WHO-VA-2022 forms; the system's own
  medical officers assign cause of death. Coding is ad hoc / pick-and-choose,
  never random allocation.
- Hierarchy per project: Project > District > Taluka/SDH (optional) >
  CHC (SMO/MO) > PHC/UPHC/AAM-PHC (MO or CHO) > Sub-centre/AAM-SHC (CHO, MPW,
  ANM) > Village (ASHA).
- Each project defines its own organization tree. At each level the project
  defines the cadres present and, per cadre, whether that cadre can **fill** a
  VA form and whether it can **code** one.
- A project-level setting fixes the **coding scope level**: the level within
  which a form may be coded (only the PHC's own deaths by its MO; or any PHC
  within the CHC; or within the Taluka; and so on).
- A project-level setting says whether levels **above** the scope level may
  also code any form, or are **viewers only** of coded forms.
- Incoming ODK forms must be **routed** to the right unit.
- Master data (units, cadres, permissions, assignments) must be exportable.
- Each unit carries: name, address, phone (optional), latitude/longitude,
  Google Maps URL, remarks (optional).

## Current state (verified 2026-09-17)

- Organization is two-level: `va_project_master` > `va_site_master` joined by
  `va_project_sites` (coding gates: `coding_enabled`, start/end dates,
  `daily_coder_limit`). One ODK form per project-site in `map_project_site_odk`
  (carries `form_type_id`; enforced one project-site per ODK form). Sync
  materializes legacy `va_forms` rows; every submission points at
  `va_forms.form_id`, so a submission's site is the form's site.
- Access: `va_user_access_grants` = role × scope, scope being `global`,
  `project` or `project_site` (DB check constraints). Roles: admin, project_pi,
  site_pi, data_manager, collaborator, coder, coding_tester, reviewer
  (`docs/policy/access-control-model.md`).
- Coder eligibility: `current_user.get_coder_va_forms()` resolves grants to a
  set of form IDs; pick-and-choose lists submissions on those forms
  (`app/routes/coding.py`, `app/services/coder_workflow_service.py::get_pick_available_forms`).
- Sync already stores per submission `SubmitterID`, `SubmitterName`,
  `DeviceID` from ODK Central (`va_data_sync_01_odkcentral.py` ~line 414).
- The WHO-VA-2022 form payload carries `Site` (site of interviewer),
  `survey_state`, `survey_district`, and free-text `Id10057` (where death
  occurred). No structured facility or village field exists today.

## Target model

### 1. Organization tree per project

- `mas_org_level` — the level definitions of one project's tree:
  `org_level_id`, `project_id`, `level_code` (e.g. `district`, `taluka`,
  `chc`, `phc`, `subcentre`, `village`), `level_name`, `depth` (1..n, unique
  per project), `is_optional`, `is_active`, sort/timestamps. Depth order is
  the only hierarchy rule; "Taluka optional" means a CHC may hang directly
  off a District.
- `mas_org_unit` — the nodes: `org_unit_id`, `project_id`, `org_level_id`,
  `parent_org_unit_id` (nullable for top level), `unit_code` (unique per
  project, stable business key used in exports and routing), `unit_name`,
  `address`, `phone`, `latitude`, `longitude`, `google_maps_url`, `remarks`,
  `is_active`, timestamps, plus a materialized `path` (ltree or a
  `/`-joined code path) for fast subtree queries. Constraint: parent's level
  depth < child's level depth within the same project.
- `mas_cadre` — cadres per project: `cadre_id`, `project_id`, `cadre_code`
  (`smo`, `mo`, `cho`, `mpw`, `anm`, `asha`, ...), `cadre_name`, `is_active`.
- `map_org_level_cadre` — which cadres exist at a level and what they may
  do: `org_level_id`, `cadre_id`, `can_fill_va_form`, `can_code_va_form`,
  `can_review_va_form` (reserved), `is_active`. Unique on (level, cadre).

Sites: `va_site_master` / `va_project_sites` stay as they are for existing
projects. A health-system project uses the org tree instead of sites; the
project-site row still exists as the container for ODK mapping and coding
gates (see §4) so nothing in the legacy stack breaks.

### 2. People: which user holds which role at which unit

This is the same shape as today's grants, one level deeper: a grant is
**user × role × unit** (today it is user × role × project-site). A user may
hold several grants at different units and levels with different roles, for
example `site_pi`-equivalent oversight as SMO at a CHC and `coder` at one PHC.
Each grant carries its own data boundary: the oversight grant sees the whole
CHC subtree read-only, the coder grant may code only inside that PHC's
subtree. Nothing is inferred from position in the tree; every capability is
an explicit grant row.

- Extend `va_user_access_grants` with `org_unit_id` and `cadre_id`, scope enum
  value `org_unit`, and check constraints so `project_pi` stays project-scoped,
  `site_pi` accepts `org_unit` (oversight of a unit subtree), and `coder`,
  `reviewer`, `data_manager`, `collaborator`, `coding_tester` accept
  `org_unit`. **Done (phase 2, migration `d9e3f5a7b2c4`)**: grants resolve to
  unit subtrees in `app/services/org_grant_service.py`, the admin Access
  Grants panel has unit and cadre pickers, and the data-manager grant
  endpoints refuse unit scope. Policy:
  `docs/policy/organization-model.md#unit-scoped-grants`.
- Cadre on the grant is descriptive (decision O3). Creating a grant checks
  `map_org_level_cadre` for the unit's level: the cadre must exist at that
  level, and role `coder` requires `can_code_va_form`. The runtime
  authorization path stays `get_coder_va_forms` and friends, extended to
  resolve unit grants to submissions (see §3).
- Form fillers who never log in (CHO, ASHA, ANM) are `mas_org_unit_worker`
  rows: name, cadre, phone (optional), unit, optional DigitVA user, ODK
  submitter id / app-user name, device id. Used by routing (§4) and master
  data export; the cadre must have `can_fill_va_form` at that level.
- The user-management panel gains a unit picker (tree) next to the existing
  project / project-site pickers; the grants list shows the unit path.

### 3. Project coding-scope settings (`va_project_master`)

- `coding_scope_level_id` (FK `mas_org_level`, nullable): the level within
  which coding is confined. A coder assigned at a unit **at or below** this
  level may code submissions routed to that unit's subtree only. A coder
  assigned at a unit **above** it is governed by the next setting.
- `above_scope_coding_mode`: `code_any` (coders above the scope level may
  code any submission in their subtree) or `view_only` (they see coded and
  uncoded forms read-only).
- `coding_intake_mode` must be `pick_and_choose` for org-tree projects; the
  admin API rejects `random_form_allocation` when a scope level is set.
- Existing project-site gates (`coding_enabled`, dates, daily limit) apply
  unchanged through the container project-site.

Eligibility rule, as one query: submission `S` is codeable by user `U` iff
`S.org_unit` is in the subtree of some active coder grant unit `G` of `U`,
and (`depth(G.level) >= depth(scope_level)` or `above_scope_coding_mode =
code_any`). Reviewer eligibility uses the same rule with reviewer grants.

### 4. ODK mapping and routing

Requirement added 2026-09-17: one DigitVA project accepts submissions from
**several ODK projects and forms over one ODK connection**, and every one of
those forms routes by unit codes. Today `map_project_site_odk` is unique on
(project, site), so a container project-site can hold only one ODK form.
Phase 3 relaxes this: uniqueness moves to (project, site, odk_project_id,
odk_form_id) while the existing one-project-site-per-ODK-form rule is kept,
and sync enumerates every mapping of the project. Legacy `va_forms` rows are
materialized per mapping as they are now.

- `map_project_site_odk` gains `org_unit_id` (nullable). A health-system
  project maps its ODK form(s) to a unit at any level (typically the whole
  project or a district: one Central form serves many CHOs). The existing
  one-project-site-per-ODK-form rule keeps holding through the container
  project-site.
- `va_submissions.org_unit_id` (nullable, indexed): the routed unit. Set at
  sync time and re-evaluated on payload change; never overwritten once a
  data manager has pinned it manually (`org_unit_pinned_by`, `_at`).
  **Done (phase 3a, migration `c1d4e7f9a3b6`)**: rules in
  `app/services/org_unit_routing_service.py`, applied by ODK sync and web
  intake, with the unrouted queue under
  `/api/v1/data-management/submissions/unrouted`. Decision B (form fields) is
  implemented; the submitter and device rules of options A and C are not.
  Several ODK forms per project-site (phase 3b) is still outstanding.
- Routing rules per ODK mapping, evaluated in order until one resolves,
  falling back to the mapping's own unit:
  1. `submitter`: `SubmitterID` / `SubmitterName` matches a
     `mas_org_unit_worker.odk_submitter_id` — the CHO's app user identifies
     the sub-centre. Recommended default; zero form changes.
  2. `form_field`: a configured payload key (e.g. a new `facility_code`
     select in the XLSForm, or `Site`) equals `mas_org_unit.unit_code` or a
     value in `map_org_unit_form_value`.
  3. `device`: `DeviceID` matches a worker's registered device.

#### 4a. Routing options for decision O4

| Option | How the unit is known | Form change | Strength | Weakness |
|---|---|---|---|---|
| A. ODK submitter | Each CHO/worker has their own ODK Central app user; `SubmitterID` → `mas_org_unit_worker` → unit | None | Zero form work; works for the existing forms | Breaks when devices or app users are shared; a worker moving units needs a registry update; the app-user list must be kept in step with the worker registry |
| B. Unit code in the form | Cascading `select_one` fields (district → CHC → PHC → sub-centre → village) whose choice lists are the unit codes exported by DigitVA; DigitVA reads the deepest answered code | Yes: new fields and a choices sheet (or `select_one_from_file` with a CSV attachment) | Explicit, auditable, survives shared devices; the death is attributed to the unit the interviewer chose | Tree edits need a form republish (choices) or attachment update; wrong picks are possible |
| C. Both (recommended) | B is primary; A is the fallback when the field is blank, and a cross-check otherwise | As B | Explicit attribution plus a safety net; mismatches (field says PHC X, submitter belongs to PHC Y) go to the DM unrouted/mismatch queue | Two registries to maintain |

Decision (2026-09-17): B. Field names are standardized as `org_<level_code>_code`, one per level of the project tree, so routing needs no per-project field configuration. DigitVA exports the `choices`-sheet rows (list_name per
level, `name` = unit code, `label` = unit name, filter column = parent code)
from the Organization panel so the XLSForm author never hand-types codes.
The routing rule is stored per ODK mapping as an ordered list, so a project
that cannot change its form runs with A only.

- Unresolved submissions land on the mapping's unit with
  `org_unit_resolution = 'fallback'` and appear in a data-manager "unrouted"
  queue for manual pinning. Routing is idempotent on rerun.

### 5. Master data import and export

- Admin panel "Organization" per project: level editor, tree editor with unit
  metadata (map link validated as URL, lat/long as decimals), cadre editor,
  level×cadre permission grid, worker list, routing keys.
- Export: one XLSX with sheets `levels`, `units`, `cadres`,
  `level_cadres`, `workers`, `routing_keys`, `user_grants`; also CSV per
  sheet. Import of the same workbook is idempotent (upsert on business codes,
  never deletes, deactivates missing rows only with an explicit flag), and
  produces a dry-run diff first. CLI `flask org export|import|validate`.
- PII note: worker names and phone numbers are personal data; exports are
  admin-only and logged in the admin activity log.

### 6. Effects on existing surfaces

- Coder dashboard (pick list): filter by routed unit subtree; show the unit
  name and level on each row.
- DM dashboard and KPIs: add unit as a grouping dimension (unit path in the
  analytics MV).
- Reporting and exports: `org_unit_code`, `org_unit_name`, level path columns.
- Reviewer track: same scope rule with reviewer grants.
- The ICD-11 plan's form-level classification setting stays on
  `map_project_site_odk`, so it applies per ODK form regardless of tree.

## Decisions

Confirmed 2026-09-17 unless marked open.

| # | Question | Decision |
|---|---|---|
| O1 | Fixed level set or per-project levels? | Per project (`mas_org_level`), seeded from a template for District > Taluka > CHC > PHC > Sub-centre > Village. |
| O2 | Keep sites for org-tree projects? | Yes: one container project-site per project (or district) so ODK mapping, coding gates and legacy `va_forms` keep working. |
| O3 | Cadre as authorization or as metadata? | Metadata that gates grant creation; role grants remain the single authorization path. |
| O4 | Routing key for incoming submissions | Option B: unit-code fields in the ODK form with standardized names `org_<level_code>_code` (e.g. `org_district_code`, `org_chc_code`, `org_phc_code`, `org_subcentre_code`); DigitVA reads the deepest non-empty code. Submitter matching is not used. |
| O5 | Coder above the scope level in `view_only` mode | Read access to coded and uncoded forms in the subtree; no coding actions. |
| O6 | Reviewer track | Same scope rule with reviewer grants. |
| O7 | Unit path storage | PostgreSQL `ltree`. Verified 2026-09-17: available (contrib 1.3) in the compose `postgres:17` image, not yet installed; the migration runs `CREATE EXTENSION IF NOT EXISTS ltree`. Production Postgres must ship contrib too. |
| O8 | Grant shape | User × role × unit, several grants per user allowed, each with its own data boundary (§2). |

## Migration and data-loss review

Additive only: five new tables, nullable `org_unit_id` on
`map_project_site_odk`, `va_submissions` and `va_user_access_grants`, new
enum value `org_unit`, two nullable project settings. Existing projects are
untouched (no scope level = today's behaviour). Backfill for a converted
project is a script run per project with a dry-run, never automatic.

## Phases

1. **Done 2026-09-17.** Tables, models, migration `c8d2e4f6a1b3`, seed
   template, admin Organization panel (levels, units with metadata, cadres,
   level×cadre grid, workers), export/import, `flask org` CLI, policy
   `docs/policy/organization-model.md`.
2. Grants with `org_unit` scope; user management UI; cadre gating.
3. Submission routing at sync (submitter rule first), unrouted queue, manual
   pin.
4. Coding scope enforcement in pick-and-choose, dashboards, reviewer track;
   policy doc `docs/policy/organization-coding-scope.md`.
5. Reporting dimensions and export columns.

## Verification

Unit tests for subtree eligibility (at, below, above scope; both modes),
routing resolution order and idempotence, import dry-run diff and upsert;
route tests for admin CRUD, grant constraint, coder pick list scoping;
manual walk-through with a seeded District > CHC > PHC > Sub-centre tree.

## References

- `docs/policy/access-control-model.md`
- `docs/policy/coding-workflow-state-machine.md` (intake modes, coding gates)
- `docs/planning/project-sites-forms-refactor.md`
- `docs/planning/icd11-coding-screen-integration-plan.md`
- `app/models/va_user_access_grants.py`, `app/models/map_project_site_odk.py`
- `app/services/va_data_sync/va_data_sync_01_odkcentral.py` (submitter metadata)
