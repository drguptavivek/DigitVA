---
title: Organization Model Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-19
---

# Organization Model Policy

## Purpose

Health-system deployments organize VA work along the public health hierarchy
(District > Taluka > CHC > PHC > Sub-centre > Village), not along research
sites. This policy defines how a project describes that hierarchy, who sits
where in it, and what the codes mean for ODK forms, coding scope and
reporting.

- How it is implemented, what the work turned up and what is still open:
  [Health-System Organization Model — Implementation Report](../current-state/health-system-organization-model.md)
- Roles and scopes generally: [Access Control Model](access-control-model.md)
- Planning context:
  [the plan](../planning/health-system-organization-model-plan.md)

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

The two halves then meet: a coder sees the deaths of their own units and no
others. A project may also fix the level within which coding happens — only
the PHC's own deaths, or anything within the CHC — and say whether people
above that level may code at all or only look.

Projects that do not use an organization tree are untouched by all of this
and keep working exactly as they did.

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

### Using official geography codes as unit codes

Where an official code already exists for a unit — an Indian census state code
(`06` Haryana), a district code (`088` Faridabad), an LGD code — **use it as
the unit code**. Do not hold a separate code and map between the two. The unit
code is read by three things at once: submission routing (`org_<level>_code`),
the XLSForm and web-form choice lists, and reporting. One value serves all
three; a mapping table would be a second source of truth for the thing that
must not drift.

One constraint decides how far down the tree that can go: **unit codes are
unique per project, not per level.** Official codes are not. Census state and
district codes happen not to collide with each other, so `06` and `088` coexist
safely in one project. Below district they repeat across parents — two blocks
in different districts may both be `0123` — and the second insert is rejected.

The rule:

- where the official code is unique within the whole project, use it bare
- below that, prefix with the parent using an underscore (`088_0123`), and do
  not put the bare official code in the unit code at all

Two consequences of that rule, both easy to assume wrongly later:

- **The value in `org_<level_code>_code` is not always the bare official
  code.** State and district stay bare (`06`, `088`) and so line up with the
  legacy `survey_state` / `survey_district` those forms already carry. Block
  and village do not. Anything reporting by census geography must therefore
  read the **state and district levels by name**, never "the deepest code on
  the submission".
- **Prefix with the parent, not with the full path.** `unit_code` is
  `String(32)`, and `CODE_RE` (`app/services/organization_service.py`) allows
  only `[A-Z0-9_]` — **no hyphens**, even though Postgres 17's ltree would
  accept them. So the separator is an underscore. `088_0123` fits comfortably;
  a four- or five-level prefix chain would not. Full-path codes are the one variant the column cannot
  hold — if anyone proposes them, the column is the constraint to raise.

State this when a project is seeded. It is cheaper than discovering it as a
failed import halfway through loading a state's villages.

There is no `external_code` column on `mas_org_unit` and none is planned. If a
project ever has to carry two coding systems at once, that is when to add one.

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
- A submission already attributed to a unit **keeps that attribution** when
  the unit is deactivated (decision 2026-09-18), so counts over a closed unit
  stay correct. Deactivation removes the unit from routing and from every
  grant's resolved scope; it does not rewrite history.

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

### Unit columns in submission exports

The data-manager submissions CSV carries `org_unit_code`, `org_unit_name` and
`org_unit_level_path` for the unit a submission routed to, appended after the
existing columns. Unrouted submissions, and projects with no tree, get blanks.
Inactive units still resolve, because a closed unit's name must stay readable
on the cases it collected.

**These are base headers, and base headers bypass PII redaction.**
`_filter_export_payload` in `app/services/data_management_service.py` filters
the payload dict only — the hardcoded omit list unioned with the
`mas_field_display_config.is_pii` set. Nothing added as a base column passes
through it.

A facility's code, name and level path are not personal data, so the three
columns above are safe. But `mas_org_unit` also carries `address`, `phone`,
`latitude`, `longitude`, `google_maps_url` and free-text `remarks`, and
`mas_org_unit_worker` carries worker names and phone numbers. **Do not add any
of those to an export as a base column** expecting the PII filter to catch
them; it will not. If a unit contact or a worker ever has to appear in an
export, restrict it at the point it is added, the way the organization
import/export is already restricted to admins and project PIs.

## Access

- The Organization panel and its API are available to `admin` and to
  `project_pi` for their own projects.
- Cadre permissions are **metadata that gate grant creation**; they are not
  a runtime authorization path. Runtime access comes from explicit
  user × role × scope grants (see
  [Access Control Model](access-control-model.md)).

## Unit-scoped grants

A unit-scoped grant on a project whose `project_status` is not `active`
resolves to nothing, like every other grant scope on a closed project. The
grant row is left untouched and resolves again when the project is reopened.
The rule and the shared predicate that implements it live in
[Access Control Model](access-control-model.md), "Closed Projects".

- A grant may carry `scope_type = 'org_unit'` with an `org_unit_id`. The grant
  covers that unit **and its whole subtree**, resolved through the unit's
  ltree path.
- A grant expands **downwards only**. It never confers access to anything
  above the granted unit.
- **Ancestors are visible, deliberately.** The units API
  (`GET /api/v1/organization/<project_id>/units`) returns, alongside the units
  a caller's grants reach, the units **above** them on the path to the root,
  each flagged `selectable: false`. A unit-scoped interviewer therefore learns
  the names and codes of every level above their grant — their own reporting
  line. This is deliberate: a cascading picker cannot show the levels above a
  grant as fixed context without their names, and the same chain is printed on
  any paper form. It is strictly more than a unit-scoped user could see before
  2026-09-19, so a deployment that treats the tree above a site as sensitive
  must know it. An `selectable: false` unit is context only — it is never a
  grantable choice, and submitting one as `org_unit_id` is refused by
  `web_intake_service._require_scope`, which validates against the grant-derived
  reachable set and ignores the flag entirely.
- Roles accepted at unit scope: `site_pi` (oversight of a subtree),
  `collaborator`, `coder`, `coding_tester`, `reviewer`, `data_manager`.
  `admin` stays global and `project_pi` stays project-scoped.
- A unit grant carries no `project_id` or `project_site_id`. The grant's
  project is the unit's project, and every project filter resolves it that way.
- One cadre per person per unit (decision 2026-09-18): a grant carries a single
  `cadre_id`, and there is one grant per user × role × unit.
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

## ODK form contract

The names a project's ODK form must use are **generated from its level codes**,
never chosen by the form developer. One helper in
`app/services/organization_service.py` is the single source of truth, and the
levels API, the exports, the panel and routing all read from it:

| Sheet | Value | Shape | Example |
|---|---|---|---|
| `survey` | field name | `org_<level_code>_code` | `org_phc_code` |
| `choices` | `list_name` | `org_<level_code>` | `org_phc` |
| `choices` | `name` | the unit code | `P01` |
| `choices` | `parent_code` | the parent unit's code | `C01` |

- Level codes are constrained to `^[a-z][a-z0-9_]{0,31}$`, so every derived
  name is a valid XLSForm name.
- The Organization panel's **ODK form fields** tab shows the exact `survey`
  and `choices` rows for the project, ready to copy into the XLSForm. A
  cascading level filters on `parent_code=${<parent level's field>}`; where the
  levels above it are optional, the filter coalesces down to the nearest level
  that must be answered. An optional level is `required = no`.
- `GET /admin/api/organization/<project_id>/levels` returns the applicable
  levels for a project, each with its `odk_field_name` and
  `odk_choice_list_name`; `odk-choices.csv` exports the choices rows.
- A **misnamed field is silent**: nothing errors, every submission simply falls
  back. So the panel also checks a mapped form against the expected names,
  reading the field list live from ODK Central
  (`GET .../odk-field-check?site_id=...`). The ODK project and form come from
  the project-site's mapping, never from the request, so the form checked is
  always the one submissions will arrive from. Check before data collection
  starts.
- **Sync checks too.** Each mapped form is checked once per sync run and any
  missing field is logged and written to the run's progress log, so a form
  edited in Central after setup surfaces as a warning rather than as a growing
  unrouted queue. The check is advisory: it never blocks a sync, and a Central
  failure on the field list is ignored.

## Submission routing

- A project's ODK form carries one field per level, named
  `org_<level_code>_code`, filled from the unit codes DigitVA exports. Routing
  reads those fields and takes the **deepest** one that names a live unit of
  that project at that level.
- A code that names no live unit, or that names a unit at a different level
  than the field it arrived in, is not trusted: routing keeps looking up the
  tree and logs the mismatch.
- Routing is by organization codes **only** (decision 2026-09-18). The ODK
  submitter is never used to decide a unit. The submitter's name is carried as
  data — the WHO VA form has a submitter name field, web intake records the
  submitting user, and sync promotes ODK's `SubmitterName` into
  `va_submissions.va_data_collector` — but it says who filled the form, not
  where the death belongs.
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
- Web intake refuses submission outright if a draft's unit was deactivated
  after the draft was started, rather than letting it fall back or go
  unrouted silently — see [Web Intake Policy](web-intake.md), "Submission".

## Coding scope

A project may fix the level within which a death may be coded, with
`va_project_master.coding_scope_level_id`. Leaving it NULL means no
unit-based coding scope.

- A coder granted at a unit **at or below** the scope level codes inside that
  unit's own subtree.
- A coder granted **above** the scope level is governed by
  `above_scope_coding_mode`: `code_any` lets them code their whole subtree,
  `view_only` (the default) lets them code nothing.
- `view_only` means the person **sees the cause of death and the submission
  data for their subtree, read-only, and codes nothing** (decision
  2026-09-18). Both halves are implemented.

### Per-unit coding gates

Coding can additionally be gated per organization unit, not only per
project-site. `map_org_unit_coding_gate` holds at most one row per gated
unit (`coding_enabled`, `coding_start_date`, `coding_end_date`,
`daily_coder_limit`); **no row means no gate**, never a closed unit.

- **Inheritance:** the nearest gated ancestor wins. A gate on a CHC applies
  to every PHC beneath it unless that PHC sets its own gate, which then
  governs its own subtree. Resolved with one ltree query
  (`org_grant_service.resolve_unit_coding_gates`), never a per-row walk up
  the tree.
- **Precedence against the site gate:** both apply; the stricter of the two
  wins. A unit gate can only narrow what `va_project_sites` already allows
  for that submission's site, never widen it — enabled only if both are
  enabled, the window is the intersection of both windows, and the daily
  limit is enforced as two separate ceilings (site and unit) against the
  same allocation count, never merged into one number and never
  double-counted.
- **Waivers:** `coding_tester` and PI waive unit gates exactly as they waive
  site gates today, at the same project/site granularity.
- The on-screen reason a coder sees names the specific unit when a unit gate
  is what actually blocks coding (e.g. "Coding for Yelahanka PHC ended on
  ..."), not a site-level reason that would not be true for that submission.
- A project with no organization tree is unaffected, as everywhere else in
  this policy.

See `.tasks/org-per-unit-coding-gates.md` for the full design record.

### Viewing scope

- The **viewable** unit set is the whole subtree of every active grant,
  regardless of the project's coding scope level: oversight does not shrink
  because coding does. It is resolved separately from the codeable set
  (`org_grant_service.viewable_unit_ids`), and the two are never substituted
  for one another — that separation is what stops a viewer becoming a coder.
- A read-only **area** surface lists the submissions routed to those units,
  marking which are also codeable, and opens any of them in the same read-only
  rendering the data manager sees. Coding, allocation and the pick list are
  unaffected: a unit a person may only view never yields work.
- A `vaview` action is therefore gated against the viewable set while every
  other coding action is gated against the codeable set.
- A project with no organization tree is unaffected, as everywhere else.
- The same rule governs the reviewer track, using reviewer grants.
- A project with a coding scope level must use `pick_and_choose` coding
  intake: random allocation would hand a coder submissions from outside
  their scope. The admin API refuses the combination either way round.

### What enforcement actually means

- A unit-scoped grant reaches the **forms** of its unit's project; which of
  that project's **submissions** may be opened is then narrowed by the routed
  unit. Both halves are needed: the first makes the project visible, the
  second keeps the coder inside their own units.
- The narrowing applies **only to projects with an active organization tree**.
  A project without one keeps the form-and-site model exactly as before —
  this is what makes the change safe to add to a shared filter path.
- An **unrouted** submission of a tree project is codeable by nobody until a
  data manager routes it. That is deliberate: attributing a death to the wrong
  unit is worse than leaving it in the queue.
- The check is applied in two places, because a list filter alone is not
  authorization: the pick list and dashboard counts filter by unit, and
  opening or being allocated one submission is gated separately
  (`org_grant_service.submission_within_org_scope`). Every coding and
  reviewing action passes through the gate, rather than each action
  remembering to ask.
- `coding_tester` is exempt, as it is from the site coding gates.

## Not yet implemented (later phases of the plan)

- unit dimensions in dashboards and analytics (the submission CSV export's
  unit columns are implemented — see
  [Implementation Report](../current-state/health-system-organization-model.md#open-questions))
