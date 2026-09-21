---
title: Health-System Organization Model — Implementation Report
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-21
---

# Health-System Organization Model — Implementation Report

What was built across phases 1–4, how each piece works, what the work turned
up, and what is still open. The governing rules live in
[Organization Model Policy](../policy/organization-model.md) and
[Access Control Model](../policy/access-control-model.md); where this report
and those disagree, the policy wins. Planning context:
[the plan](../planning/health-system-organization-model-plan.md).

## Why this exists

The next deployment is a public health system, not a research site network.
Community Health Officers fill WHO-VA-2022 forms and the system's own medical
officers assign cause of death, within a hierarchy of District > Taluka >
CHC > PHC > Sub-centre > Village. DigitVA's existing shape — Project > Site >
Form, with access granted per project or per site — cannot express "the MO at
this PHC codes this PHC's deaths".

Nothing here replaces that shape. Projects without an organization tree behave
exactly as they did; the tree is an alternative the project opts into.

## What is built

| Phase | Migration | What it added |
|---|---|---|
| 1 | `c8d2e4f6a1b3` | Levels, units with ltree paths, cadres, level × cadre permissions, workers, admin panel, export/import, ODK choices export, `flask org` CLI |
| 2 | `d9e3f5a7b2c4` | `org_unit` grant scope covering a unit subtree, descriptive cadre validated against the level × cadre grid |
| 3a | `c1d4e7f9a3b6` | Submission routing to units, fallback unit per ODK mapping, data-manager unrouted queue, ODK form-field contract and preflight check |
| 3b | `e2a5c8b1d7f3` | Several ODK forms per project-site, each with its own `va_forms` row |
| 4 | `f7b2d4e6a8c9` | Project coding scope level and above-scope mode, enforced in the coder and reviewer tracks |

Every migration is additive. No existing row changes meaning, and each new
column is nullable or defaults to the conservative value.

## How it works

### The tree

Rules: [Organization Model Policy → Baseline](../policy/organization-model.md#baseline) and
[Codes](../policy/organization-model.md#codes); lifecycle of a unit:
[Lifecycle](../policy/organization-model.md#lifecycle).

`mas_org_level` defines a project's levels: a `level_code`, a `depth` (1 = top)
and an `is_optional` flag. Depth is the only hierarchy rule, so "Taluka
optional" simply means a CHC may hang directly off a District.

`mas_org_unit` holds the nodes, each with a `unit_code` unique within its
project, contact and location metadata, and a materialized `path` — a
PostgreSQL `ltree` of unit codes, GiST-indexed. The path is what makes
"everything under this CHC" a single indexed predicate (`path <@ :ancestor`)
rather than a recursive walk, and it is rewritten across the subtree when a
unit is renamed or moved.

Deactivating a unit cascades to its subtree. Nothing is deleted.

A unit with no parent below the top active level is *unplaced*: the importer
may create one from a row with a blank `parent_code` (a facility list with no
hierarchy), and nothing else may. It is derived (`is_unplaced` on the unit
JSON, `organization_service.unplaced_unit_codes`), with no schema change. The
Units tab shows a banner and a *Map parents* modal, and supports dragging a
unit onto a new parent; both call `POST .../units/place`
(`organization_service.place_units`, all or nothing). The intake unit picker
leaves unplaced subtrees out and readiness warns (`org_unplaced`). Rules:
[Unplaced units](../policy/organization-model.md#unplaced-units).

Which projects may have a tree at all is explicit:
`va_project_master.project_structure_mode` is `sites` (default) or
`organization` (migration `a4c7e2f9b1d6` backfilled `organization` for
projects that already had org rows). The admin organization API refuses every
write for a `sites` project in its shared `_guard`
(`app/routes/admin_organization.py`, via
`organization_service.require_organization_mode`), and the Organization panel
lists only `organization` projects. An `organization` project gets one
automatic site (`Sites_in_project_<id>`, code `O###`) from
`organization_service.ensure_organization_site`, called by project create and
update in `app/routes/admin.py` and by `flask org ensure-site`. Rules:
[Project structure mode](../policy/organization-model.md#project-structure-mode).

### People

Rules: [Unit-scoped grants](../policy/organization-model.md#unit-scoped-grants) for what a grant may
carry and how the cadre is validated; [Scope Model](../policy/access-control-model.md#scope-model) and
[Role To Scope Rules](../policy/access-control-model.md#role-to-scope-rules) for how `org_unit` sits
beside the other scopes; [Grant Storage Baseline](../policy/access-control-model.md#grant-storage-baseline)
for the stored shape.

Two distinct populations, deliberately not conflated:

- **Workers** (`mas_org_unit_worker`) are the people who fill forms — CHO, ASHA,
  ANM. Most never log in. They exist for the master data and for future
  submitter-based routing.
- **Grants** (`va_user_access_grants`) are the people who use DigitVA. A grant
  is user × role × scope, and the scope may now be `org_unit`: one node, whose
  subtree the grant covers.

A grant may carry a `cadre_id`. It is **descriptive** — nothing at runtime
reads it — but it is validated on write against the level × cadre grid: the
cadre must exist at that unit's level, and a `coder` grant requires a cadre
with `can_code_va_form` there. The keycard analogy in the policy doc: the role
is the kind of card, the scope is the doors it opens, the cadre is the job
title printed on the front, checked when the card is issued and never re-read
by the door.

### Enforcement

Rules: [Coding scope](../policy/organization-model.md#coding-scope), and
[Authorization Rule](../policy/access-control-model.md#authorization-rule) for the general requirement
that every request pass role *and* scope.

Two halves, because a list filter is not authorization:

1. A unit grant reaches the **forms** of its unit's project
   (`va_users._get_granted_va_forms`), which is what makes the project visible
   at all.
2. The **submissions** of those forms are then narrowed to the coder's own
   units (`coder_workflow_service._org_unit_scope_filter`), and opening or
   being allocated one submission is gated separately
   (`org_grant_service.submission_within_org_scope`).

The per-submission gate runs once at the top of the coding and reviewing
validators in `va_validate_permissions`, rather than per action, so a future
action cannot forget to ask.

The project's `coding_scope_level_id` then narrows which grants count at all:
a coder granted at or below that level codes their own subtree; one granted
above it codes their subtree only when `above_scope_coding_mode = 'code_any'`,
and otherwise codes nothing. A project with a scope level must use
pick-and-choose intake, since random allocation would hand a coder work from
outside their scope.

**The narrowing applies only to projects with an active organization tree.**
This is the single most important property of the implementation: the filter
excludes nothing for a project without one, which is what made it safe to add
to a query path every coder uses.

## How routing works

Rules: [Submission routing](../policy/organization-model.md#submission-routing) and
[ODK form contract](../policy/organization-model.md#odk-form-contract).

Routing is how a death arriving from ODK Central is attributed to a unit. It
is the hinge between the tree and everything else: without it, units describe
an organization that no submission belongs to.

### The form contract

Rules: [ODK form contract](../policy/organization-model.md#odk-form-contract).

A project's ODK form carries **one field per level**, named from the level
code. The names are generated, never chosen:

| Sheet | Value | Shape | Example |
|---|---|---|---|
| `survey` | field name | `org_<level_code>_code` | `org_phc_code` |
| `choices` | `list_name` | `org_<level_code>` | `org_phc` |
| `choices` | `name` | the unit code | `P01` |
| `choices` | `label` | the unit name | PHC One |
| `choices` | `parent_code` | the parent's unit code | `C01` |

One helper in `organization_service` is the single source of truth, and the
levels API, the exports, the admin panel and the routing code all read from
it. Level codes are constrained to `^[a-z][a-z0-9_]{0,31}$`, so every derived
name is a valid XLSForm name.

The Organization panel's **ODK form fields** tab shows the exact rows to copy
into the XLSForm, including the `choice_filter` for each cascading level. Where
the levels above are optional the filter coalesces down to the nearest level
that must be answered — `parent_code=coalesce(${org_taluka_code},
${org_district_code})` — so an optional Taluka does not break the cascade.

### The resolution rule

Rules: [Submission routing](../policy/organization-model.md#submission-routing).

At sync time, for every created or changed submission
(`org_unit_routing_service`):

1. Read every `org_<level_code>_code` field present in the payload.
2. Take the **deepest** one that names a live unit of that project **at that
   level**. A code naming a unit at a different level than the field it
   arrived in is not trusted: routing logs the mismatch and keeps looking up
   the tree.
3. Failing that, fall back to the unit named on the submission's ODK form
   mapping (`map_project_site_odk.org_unit_id`) — typically a district, for a
   project whose single Central form serves many interviewers.
4. Failing that, leave the submission **unrouted**.

Codes are matched case-insensitively, and read whether ODK delivers the field
bare or inside a group path (`.../org_phc_code`), because Central flattens
group paths and a payload key arrives the same way.

`va_submissions.org_unit_resolution` records which of the three happened:
`form_field`, `mapping_fallback`, or `manual`.

### Properties that make it safe to rerun

- **Idempotent.** The same payload always yields the same unit, so re-running
  a sync rewrites nothing.
- **Re-evaluated on change.** A corrected form moves the death to the right
  unit on the next sync.
- **A manual pin wins.** A data manager's decision sets `manual` and no later
  sync overwrites it. Clearing the pin hands the submission back to routing.
- **No tree, no routing.** A project without levels is skipped entirely.
- **Cheap.** A `RoutingContext` is built once per form and caches the
  project's levels and its unit-code lookups, so a form's thousandth
  submission costs no more queries than its first.

Web-intake submissions route by the same rules: the web questionnaire carries
the same fields and the project-site's mapping supplies the same fallback.

**Web submissions route identically to ODK ones.** The web draft's
`_unit_context` (`web_intake_service.py:292-308`) resolves the interviewer's
unit the same way ODK submissions do, filling `org_<level_code>_code` from it
rather than through a separate path; an end-to-end test of the routing lands
as WP3 (`tests/routes/test_intake_org_routing_e2e.py`).

### When routing fails

An unrouted submission of a tree project is codeable by **nobody** until a
data manager routes it. This is deliberate — attributing a death to the wrong
unit is worse than leaving it in a queue — and it is why the queue exists:

- `GET /api/v1/data-management/submissions/unrouted` lists what did not
  resolve inside the manager's granted scope, including submissions sitting on
  a mapping fallback rather than their own unit.
- `POST /api/v1/data-management/submissions/<va_sid>/org-unit` pins a unit or
  clears the pin. Pins are audited.

### Setting routing up, in order

1. Build the tree in the Organization panel, or import the workbook. Seed the
   template first if the standard hierarchy fits.
2. Open **ODK form fields** and copy the `survey` and `choices` rows into the
   XLSForm. Publish the form to Central.
3. Map the form to a project-site in Project Forms, and set a **fallback
   organization unit** if unrouted submissions should land somewhere rather
   than wait in the queue.
4. Run the **check** in the ODK form fields tab: it reads the mapped form's
   field list from Central and reports each expected field present or missing.
   Do this before data collection, because a misnamed field is silent.
5. Grant coders at their units, with a cadre allowed to code at that level.
6. Set the project's coding scope level and above-scope mode.

### What routing does not do yet

The plan considered three routing strategies. One is built; the other two are
**closed, not deferred**.

| Option | Mechanism | Status |
|---|---|---|
| A. ODK submitter | `SubmitterID` → worker registry → unit | **will not be built** (2026-09-18) |
| B. Unit code in the form | `org_<level_code>_code` fields | **built** |
| C. Both, with mismatch detection | B primary, A as fallback and cross-check | **will not be built** (2026-09-18) |

Routing is by organization codes only. A submission's unit comes from what the
interviewer answered, and from nothing else.

The submitter's **name** is still carried, as data rather than as a routing
key: the WHO VA form has a submitter name field, web intake records the
submitting user, and sync promotes ODK's `SubmitterName` into
`va_submissions.va_data_collector`. It says who filled the form; it does not
decide which unit the death belongs to.

This closes the worker-registry question too: `mas_org_unit_worker` needs no
ODK submitter or device columns, and nothing has to be reconciled against
Central's app-user list. Workers remain master data — who works where, in
which cadre — and the form-filling permission in the level × cadre grid.

## Findings

Things the work turned up that were not in the plan.

**`va_forms` was keyed by project-site alone.** Mapping a second ODK form to a
project-site rewrote the first form's row in place, so every submission
collected under the old form would silently claim to belong to the new one.
This was the real content of phase 3b; the uniqueness constraint was the
trivial part. Four other places resolved a mapping from a project-site alone
and became ambiguous the moment a pair held two: the runtime-form lookup, the
ICD classification for a submission, the DM sync-stats join, and the DM "edit
in ODK" link.

**`va_forms.odk_project_id` is text while the mapping's is an integer.** Every
join between them has to cast. Worth knowing before writing the next one.

**A shared filter was used by queries that do not join `va_forms`.** The first
version of the coding-scope filter correlated a subquery on `VaForms`, which
would have added a silent cartesian product to the dashboard counts. It now
correlates on `va_submissions` alone with `va_forms` pulled inside the
subquery.

**`admin_update_project` applied fields as it parsed them.** An error from a
later field left the earlier ones on the ORM object, where a flush could
persist a partial update nobody asked for. Now every field is validated before
any is applied.

**A migration test seeded through the ORM at an older revision.** Adding
columns to `va_submissions` broke it. `tests/migrations/test_attachment_state_backfill.py`
now uses SQL with explicit columns, the pattern it already applied to
`va_forms` and the attachment rows. Any future column on those tables would
have hit the same trap.

**The metadata naming convention double-prefixes check constraints.** With
`ck: "ck_%(table_name)s_%(constraint_name)s"`, a migration that passes the
full name gets `ck_va_user_access_grants_ck_va_user_access_grants_...`.
Cosmetic, invisible to the drift guard (autogenerate ignores check
constraints), but it accumulates.

**Operational.** `minerva_app` is capped at 756 MiB and idles near 77% of it,
so a single-process full `pytest` run is OOM-killed partway with no summary;
the suite has to be run in slices. Two sessions running pytest at once collide
on the shared test database and produce failures that do not reproduce.

## Open questions

Anything settled here belongs back in
[Organization Model Policy](../policy/organization-model.md) before it is
implemented.

### Decided (2026-09-18)

1. **A project needs both sites and a tree.** The container project-site
   stays, carrying the ODK mapping and the coding gates (`coding_enabled`,
   dates, `daily_coder_limit`), with the tree alongside it. This is what is
   built, so nothing changes. Whether those gates are also wanted per unit is
   tracked separately below.
2. **Units are never deleted.** Deactivation only, and a submission already
   attributed to a unit keeps that attribution. This is what is built:
   deactivation cascades to the subtree, nothing is removed, and coded deaths
   stay where they were counted. Reporting over a closed unit therefore stays
   correct.
3. **`view_only` means the person sees the cause of death and the submission
   data, but codes nothing.** Both halves are now implemented: the viewable
   unit set is resolved separately from the codeable one, a read-only **My
   Area** surface lists the subtree's submissions and opens them in the data
   manager's read-only rendering, and a `vaview` action is gated against the
   viewable set while every other coding action stays gated against the
   codeable one.

4. **One cadre per person per unit.** A grant carries one `cadre_id`, and
   there is one grant per user × role × unit. That is the model, and it is
   what is built — nothing to change.
5. **Routing is by organization codes only.** Submitter-based routing
   (options A and C) is **not** going to be built. The submitter's name is
   still carried as data — the WHO VA form has a submitter name field and web
   intake records one — but it plays no part in deciding a submission's unit.
   The worker registry therefore needs no ODK submitter or device columns.
6. **Coding gates are wanted per unit**, not only per project-site: a coding
   window, an enabled flag and a daily limit for one PHC rather than for the
   whole site. Not built; the design questions — inheritance down the subtree,
   and precedence against the existing site gate — are in
   `.tasks/org-per-unit-coding-gates.md`.
7. **The ODK form check runs during sync.** Implemented: each mapped form is
   checked once per sync run against the project's expected
   `org_<level_code>_code` fields, and missing ones are logged and written to
   the run's progress log. It is advisory — it never blocks a sync, and a
   Central failure on the field list is ignored.

### Still open

8. **Reporting dimensions (phase 5).** Split in two:
   - **Exports — done.** `dm_submissions_export_csv` (the data manager's
     `submissions/export.csv`) now appends `org_unit_code`, `org_unit_name`
     and `org_unit_level_path` (the human-readable ancestor chain, e.g.
     `Bengaluru Urban / North Block / Yelahanka PHC`) after every existing
     column, base and payload-derived alike, so no downstream consumer's
     column offsets shift. A project without a tree, or a submission that
     was never routed, exports the three columns blank — nothing else
     changes. Resolution is batched:
     `organization_service.resolve_org_unit_export_labels` takes the distinct
     `org_unit_id`s already present in the fetched rows and runs exactly two
     queries regardless of row count — one for those units, one for the
     ancestor unit codes named in their `path` (deduplicated project-wide) —
     so a large export never walks the tree per row. Inactive units still
     resolve their code and name.
   - **Unit path in the analytics MV, unit as a grouping dimension in the DM
     KPIs — not started.** Listed under
     [Not yet implemented](../policy/organization-model.md#not-yet-implemented-later-phases-of-the-plan).

## Verification

- Tests added across the phases cover the tree rules, path rewrites, cadre
  gating, subtree resolution, routing including four cases driven through the
  real sync upsert loop, the ODK field preflight both on demand and during
  sync, several forms per project-site, the coding-scope rule in all four
  positions relative to the scope level, and the viewing right — including
  that a viewable-but-not-codeable submission is still refused by allocation
  and absent from the pick list.
- Full suite passing, including the schema drift guard, which builds a
  database from the migration chain alone and compares it to the models.
- Migrations applied and cycled on the development database.

## Web form options API

`GET /api/v1/organization/<project_id>/form-options` sits on the same
blueprint as `/units`, with the same decorators (`login_required` plus the
120/minute limiter) and the same grant check: a signed-in user with no grant
reaching the project gets 403, an unknown or deactivated project 404. Unlike
`/units` the body is *not* narrowed by what the caller's grants reach —
project configuration is the same for everyone who may see the project.

It serves the tier-2 options of `docs/policy/va-web-form-options.md`:
`form_types` (with exactly one `is_default`), `default_locale`,
`available_locales`, `narration_languages`, `show_guidance`, a derived
`enabled_extensions`, and a `config_version` that moves — exactly like
`tree_version` — when the project row, its `map_project_site_odk` rows, or the
form types they reach change.

Geography is deliberately not repeated here: it is the tree served by
`/units`, and duplicating it would create two sources for the codes that drive
routing.

Four columns on `va_project_master` back it (migration `f2a9c4d7e1b3`,
additive, reversible):

| Column | Type | Null | Meaning |
|---|---|---|---|
| `web_intake_default_locale` | `String(16)` NOT NULL, default `'en'` | — | The language the form opens in |
| `web_intake_available_locales` | JSONB list of codes | yes | NULL = every active `mas_languages` row |
| `web_intake_narration_languages` | JSONB list of codes | yes | NULL = none offered |
| `web_intake_show_guidance` | Boolean NOT NULL, default false | — | Whether source guidance notes render |

They are read and written by the project settings serializer and
`PUT /admin/api/projects/<project_id>`, which validates every code against the
active language list. The admin projects panel UI is unchanged — the panel is
JS-driven and these need more than a plain input each.

`app/templates/va_frontpages/va_intake_form.html` fetches the endpoint after
bootstrap and uses it for the `locale` attribute, the `show-guidance`
attribute, and the `instrument` property, which it looks up by the default
form type's `form_type_code`. A form type with no bundled instrument is an
error shown in the page's alert box, never a WHO 2022 form rendered under
another name.

Since 2026-09-21 (`digitva-mxn`) the page's locale bar also carries a "Show
English" switch that sets the component's `show-english` attribute, so the
English renders as a muted `lang="en"` line beneath translated question
labels, hints and choice labels. It is hidden for `en`, on by default, and
remembered per browser (`localStorage` key `digitva.intake.showEnglish`). For a
locale whose `available_locales` entry has `under_review: true` it is checked
and disabled, with a note, without overwriting the remembered choice.

## Where the code lives

| Concern | Module |
|---|---|
| Tree, cadres, workers, export/import, unit label lookup for submission exports | `app/services/organization_service.py` |
| Organization tree and web form options JSON API | `app/routes/api/organization.py` |
| Unit-scoped grants, coding scope rule | `app/services/org_grant_service.py` |
| Submission routing, ODK field preflight | `app/services/org_unit_routing_service.py` |
| Runtime form materialization per mapping | `app/services/runtime_form_sync_service.py` |
| List filtering and the allocation gate | `app/services/coder_workflow_service.py` |
| Per-action enforcement | `app/decorators/va_validate_permissions.py` |
| Read-only area overview | `app/routes/coding.py` (`area_overview`) |
| Organization admin API | `app/routes/admin_organization.py` |
| Unrouted queue | `app/routes/api/data_management.py` |
