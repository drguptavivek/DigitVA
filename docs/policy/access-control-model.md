---
title: Access Control Model
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-03
---

# Access Control Model

## Core Rule

DigitVA uses a hybrid RBAC and ABAC model.

- role defines capability
- scope defines boundary
- access is granted only when both match

In other words:

- RBAC answers: what can this user do?
- ABAC answers: where can this user do it?

## Roles

DigitVA uses these roles:

- `admin`
- `project_pi`
- `site_pi`
- `data_manager`
- `collaborator`
- `collaborator_pii`
- `coder`
- `coding_tester`
- `reviewer`
- `interviewer`
- `interview_supervisor`

Roles are additive and do not inherit from each other.

## Role Meaning

### `admin`

Global administration.

May manage:

- users
- projects
- sites
- project-site mappings
- integrations
- all application records

### `project_pi`

Project-wide oversight within assigned projects.

May, in every project:

- view data across all assigned sites in an assigned project
- view reporting for an assigned project
- perform oversight actions allowed by workflow policy
- set up the project and grant roles in it (see
  [Organization Model Policy](organization-model.md), "Spreadsheet setup")

In an **organizational (unit-tree) project** the `project_pi` additionally:

- sees every screen of the project, with personal data: the data-management
  dashboard, grid, KPIs and submission view, the coder and reviewer views,
  the area view, intake supervision and the site PI report
- may act as `data_manager` and `interview_supervisor` across the whole
  project: triage and not codeable, routing and pinning a submission to a
  unit, sync, screening, upstream-change resolution, the unrouted queue and
  intake supervision actions

Implemented for the data-management screens and actions (dashboard, grid,
KPIs, submission view, triage, sync, routing and pinning, the unrouted
queue) in digitva-0wc stage 3; intake supervision and the site PI report
(every site and the top-level units of the project) in stage 5.

Coding and reviewing still require a `coder` or `reviewer` grant. In a site
(non-tree) project the `project_pi` keeps only the powers in the first list.

### `site_pi`

Site-specific oversight within assigned project-site scope.

May:

- view data for assigned sites within assigned projects
- view reporting for assigned project-site scope
- perform oversight actions allowed by workflow policy

A user may hold `site_pi` grants for many project-site pairs.

### In-charge (organizational projects)

Decision 2026-10-02. An organizational (unit-tree) project has one
**In-charge** role, held at every level of the tree: the **District
in-charge** (CMO or Civil Surgeon) on a district unit, the **Block in-charge**
(Senior Medical Officer, CHC) on a block unit, and the **PHC in-charge**
(Medical Officer, PHC) on a PHC unit. It replaces both the "District lead"
recorded earlier the same day and the display name "field supervisor" for
`interview_supervisor`. Within their own unit subtree every in-charge:

- sees every screen, with personal data: the data-management dashboard,
  grid, KPIs and submission view, the coder and reviewer views, the area
  view, intake supervision and the site PI report
- oversees field work, as `interview_supervisor` does today: views intake
  cases, resolves flags, cancels or reopens a case and marks duplicates (see
  [Web Intake Policy](web-intake.md), "Supervisors")
- has every power of a `data_manager` in that subtree: triage and Not
  Codeable, screening, sync, route and pin, the unrouted queue, upstream
  change resolution, and the grants a data manager may give
- creates `data_manager` grants on their own unit and on units beneath it,
  and the grants a data manager gives anywhere in their area (see "Who
  creates which grants")

Coding and reviewing still require a `coder` or `reviewer` grant. Mentoring
institute members may never hold the role; cadre validation applies as for
any unit grant.

The In-charge is the `site_pi` role held at `org_unit` scope, shown as
"In-charge" (decision 2026-10-02). The `role_scope` CHECK allows it
(migration `e2b7c4d9a1f3`) and the grant validator accepts it on a unit of a
project with an organization tree only; a cadre is optional and, when
given, must be defined at the unit's level. Classical projects keep
`site_pi` at `project_site` unchanged. In an intake supervision audit row
an In-charge grant ranks with `interview_supervisor` at equal depth.

Implemented in digitva-0wc stage 5: the screens, data-manager actions,
intake supervision and the site PI report for the in-charge's own units.
Single-submission sync only: whole-form sync stays with project and site
data managers. The grant-creation powers above are implemented in
digitva-0wc stage 6. A person who holds only an `interview_supervisor`
grant has only its powers.

### `data_manager`

Data-quality and operational triage role within assigned scope.

May:

- browse all submissions within assigned scope
- open submissions in read-only mode
- document that a submission is not codeable from a data-management perspective
- view reporting and workflow context needed to diagnose submission quality issues
- create grants within their own scope, as set out in "Who creates which
  grants": today's rule in site projects; in district projects the subtree
  rule

May not:

- start coding
- submit COD assessments
- submit reviewer QA
- take coder-only or reviewer-only workflow actions

### `collaborator`

Read-only role within assigned scope.

May:

- view data
- view reporting
- open a single submission read-only, within scope, with personal data
  redacted (`authz.require(VIEW)`, digitva-0wc). The read-only renderings
  (`vadata`, `vaarea`) load the category sections plus an allowlist of other
  partials (workflow history, the viewer's own note); the coding forms, which
  carry the DORIS prefill and prior certificates, are refused, and the DORIS
  prefill is skipped for any redacting viewer

May not:

- code
- review
- perform oversight write actions
- administer configuration
- **see personal data.** Payload fields flagged `is_pii` in
  `mas_field_display_config` are redacted, and so is staff identity — who
  collected, coded or reviewed a death. Use `collaborator_pii` for that.

#### Rollout note: this narrows an existing role

Before the viewer split, a `collaborator` saw whatever a screen rendered,
personal data included. Making the plain role no-PII **removes** visibility
from every grant that already exists.

That is the safe direction and it is deliberate — the alternative, defaulting
existing grants to PII, would keep an unreviewed set of people seeing personal
data because of how the roles happened to be numbered. But it is not silent:
existing `collaborator` holders who genuinely need personal data must be
re-granted as `collaborator_pii` by an admin or project PI, as a decision about
each person, and the migration must not do it for them.

### `collaborator_pii`

Read-only role within assigned scope, **including personal data**. Shown in
the admin panel as "Viewer (with PII)"; plain `collaborator` is shown as
"Viewer".

Identical to `collaborator` in everything it may do, including opening a
single submission read-only within scope (`authz.require(VIEW)`,
digitva-0wc). The only difference is that personal data is not redacted from
what it sees. Mentors, who may hold `collaborator_pii`, open submissions the
same way.

May additionally see:

- the personal-data fields of a submission payload — those flagged
  `is_pii` in `mas_field_display_config` (names, the national identification
  number, the ABHA identifiers)
- staff identity: who collected, coded and reviewed each death
  (`va_submissions.va_data_collector`, the payload's `SubmitterName`, and the
  coder and reviewer names on workflow and audit views)

Grant it for the operational reason it exists: a supervisor who has to know
who did what for which death. It is not a convenience upgrade of
`collaborator` and should be granted deliberately, to named people.

#### Why this is a role and not a flag

Considered and rejected: a `sees_pii` boolean on the grant. Roles were chosen
so that PII visibility is legible wherever a grant is listed, audited or
reviewed, rather than hidden in a column somebody has to know to look at.

The cost is real and should be understood: every place that tests
`role == collaborator` must also test `collaborator_pii`, and a place that
forgets fails **closed** for `collaborator_pii` (a supervisor sees too little)
but a place that tests only "is read-only" and forgets to redact fails **open**
(a plain viewer sees PII). Redaction is therefore written as a single helper
that takes the viewer's role, never as a per-screen condition.

#### One PII set, or two

`collaborator_pii` currently carries **both** subject personal data (the
deceased, the respondent) and staff identity (the interviewer, the coder). The
two are governed differently — subject data sits under ethics approval, staff
names are ordinary personnel data — and a supervisor who needs only the audit
trail must today be given the deceased's name as well.

If that trade proves wrong in practice, the split is a third role
(`collaborator_staff`), which is exactly the cost of using roles as the
mechanism. Recorded here so the choice is revisited deliberately rather than
rediscovered.

#### The PII set must be confirmed per form type

Redaction keys on `mas_field_display_config.is_pii`, and an unflagged field is
indistinguishable from a field nobody has classified. That silence is not a
safe default: `apply_pii_field_registry` applies a WHO-keyed field list to
*every* form type, so a non-WHO questionnaire (PHMRC, Ballabgarh) receives
three redaction-only rows for field ids it does not contain while its own name
and identifier fields stay unflagged.

So a form type's PII set counts as **confirmed** only when at least one field
the form type *owns* carries `is_pii = true` — a row that is mapped
(`subcategory_code`), synced from ODK (`odk_label`), or otherwise not created
by the registry (`is_custom = false`). The rule is derived from the rows on
every read (`FieldMappingService.get_pii_set_status`); nothing is stored, so
there is no state to migrate or to fall out of date.

Unconfirmed fails closed:

- the submission detail render withholds the **entire** payload from a viewer
  subject to redaction, not just the flagged fields, and logs
  `pii set unconfirmed | <form_type_code> | payload withheld`
- `_filter_export_payload` returns `{}` for every submission on that form, so
  the submissions CSV export carries no payload values. Column shape is
  unchanged — the headers still come from the confirmed forms in the same
  export and the withheld rows write those columns empty, per "empty the
  column, never drop it" below.

One export is exempt. The **SmartVA input export** passes
`withhold_unconfirmed=False` and keeps stripping only the flagged `is_pii`
fields, exactly as it did before the set became confirmable. Withholding there
would leave SmartVA unable to process any new questionnaire at all, and the
export is a data_manager/admin processing feed rather than a viewer surface —
it is already reachable only by roles that may see full submission data. It
logs one warning per form instead:
`pii set unconfirmed | <form_type_code> | smartva input export not withheld`.
The exemption is a parameter at that one call site so it stays greppable; the
submissions CSV export keeps the default, which is consistent because it was
already PII-filtered for every role.

An admin confirms the set by flagging one owned field **Is PII** in the
admin field-mapping panel. Until then that form type's card in the panel
carries a standing warning, `GET /admin/api/form-types` reports
`pii_set_confirmed: false`, and `flask form-types stats` says so.

Activation and creation of a form type are deliberately *not* blocked on this:
a form type has no fields at registration time, so the working order is
register -> ODK sync -> flag.

#### Redaction rules for viewer-reachable surfaces

A surface a viewer reaches redacts through `should_redact_pii`, never through
a per-screen role test. Which routes a viewer reaches today, and which
surfaces redact what, is recorded in
[Workflow And Permissions](../current-state/workflow-and-permissions.md),
"Viewer route reach and export redaction".

- **Empty the column, never drop it.** Downstream consumers of the
  submissions export depend on its column order and offsets, so a redacted
  export has the same shape as an unredacted one.
- **Coder daily statistics return no rows rather than pseudonymous ones** to
  a viewer subject to redaction. Every row of that panel *is* staff identity.
  Blanking the name would leave `coder_id` as a stable per-person key across
  days and across exports — the same disclosure by another route.

##### Blocker: `narrative_text` blocks wiring the snapshot export to viewers

**Do not grant `collaborator` the coded-COD snapshot export until
`narrative_text` is resolved.** Its staff-identity columns are redacted;
`narrative_text` is not, and it is the column that carries the deceased's
name.

`narrative_text` is the free-text death narrative. It routinely contains the
names of the deceased, the respondent and the attending clinician, in prose,
where no field-level flag reaches them. It is subject personal data governed
by `is_pii` on the payload field, not staff identity, so it must not be filed
under `COD_SNAPSHOT_STAFF_IDENTITY_HEADERS`. The submissions export carries
the same narrative, so redacting it on one export alone would be an
inconsistent half-change.

The failure this blocker exists to prevent: the staff columns look handled,
so the export reads as safe to widen, and a plain viewer gets the deceased's
name in free text on the first row.

Resolving it is the `is_pii` decision, applied consistently across both
exports.

### `coder`

Coding role within assigned scope.

May:

- start coding
- resume owned coding
- submit coding outcomes
- view coding records when allowed by workflow policy

Coder eligibility guard:

- coder-visible forms must resolve to an active project-site mapping in
  `va_project_sites`
- if a site is moved between projects and the old project-site row is
  deactivated, old forms from that deactivated pair are excluded from coder
  access and random allocation

### `reviewer`

Secondary coding role within assigned scope.

May:

- start reviewer coding when allowed by workflow policy
- resume owned reviewer coding
- submit reviewer COD outcomes
- view reviewer records when allowed by workflow policy

Current workflow-policy note:

- reviewer participation is optional and sample-based
- reviewer coding opens only after the coder's 24-hour recode window closes
- reviewer is a coding authority, not just an accept/reject QA overlay

### `coding_tester`

Coding role for exercising the coding workflow within assigned scope.

May:

- code submissions in scope to check that coding works, including while
  coding gates are closed

Rules:

- its coding does not count toward results or real workflow counts (see
  [Auth Decorator and RBAC Gating Policy](auth-decorator-rbac.md))
- tester output is stored marked as tester output and never becomes the
  case's result: when a tester finishes coding a real submission, the
  submission returns to the coding pool (`ready_for_coding`) for a real
  coder; tester output is left out of every coder, DM and burndown count and
  never makes a case reviewer-eligible (owner decision 2026-10-03,
  `digitva-ggc3`)
- it waives coding gates — site gates and per-unit gates — but **never
  scope**: a tester codes only submissions its grants cover, and a unit
  tester waives gates only within its own subtree (see
  [Organization Model Policy](organization-model.md), "Per-unit coding
  gates")
- the coder eligibility guard is scope, not a gate: a tester neither views
  nor codes forms of a deactivated (project, site) pair (security review 10
  #5); demo-training practice is unaffected

May not:

- review
- grant roles

### `interviewer`

Data-collection role within assigned scope.

May:

- register deaths and interview respondents through web intake or the mobile
  app, for the projects, sites and units its grants reach
- see and follow up its own cases

May not:

- code or review

See [Web Intake Policy](web-intake.md).

### `interview_supervisor`

Supervision role for web intake, held at `org_unit` scope only.

May:

- view the web intake cases in its unit subtree, confirm or reject
  duplicate and cancel flags, and reopen terminal cases; a supervisor never
  assigns

May not:

- interview, code or review without the matching grant

See [Web Intake Policy](web-intake.md), "Supervisors".

## Scope Model

Authorization scope must be explicit.

Supported scope types:

- `global`
- `project`
- `project_site`
- `org_unit`

Rules:

- `global` means system-wide access
- `project` means access across all sites within that project
- `project_site` means access only to one site within one project
- `org_unit` means access to one node of a project's organization tree **and
  its whole subtree**; the node's project is the grant's project. Used by
  health-system projects — see
  [Organization Model Policy](organization-model.md)

Broad access must be granted explicitly.

The system must not infer broader access from missing values or partial keys.

## Role To Scope Rules

- `admin` uses `global`
- `project_pi` uses `project`
- `site_pi` uses `project_site`, or `org_unit` in an organizational project,
  where it is the **In-charge** (see "In-charge"; database `role_scope`
  CHECK since migration `e2b7c4d9a1f3`)
- `data_manager` uses `project`, `project_site` or `org_unit`
- `collaborator` uses `project`, `project_site` or `org_unit`
- `collaborator_pii` uses `project`, `project_site` or `org_unit`
- `coder` uses `project`, `project_site` or `org_unit`
- `coding_tester` uses `project`, `project_site` or `org_unit`
- `reviewer` uses `project`, `project_site` or `org_unit`
- `interviewer` uses `project`, `project_site` or `org_unit` (see
  [Web Intake Policy](web-intake.md))
- `interview_supervisor` uses `org_unit` only (database `role_scope` CHECK);
  it supervises web intake cases in the unit's subtree, as do `data_manager`
  grants in their own scope (see [Web Intake Policy](web-intake.md), "Supervisors").
  The In-charge is `site_pi` at `org_unit`, not this role (see "In-charge")

A unit grant of `data_manager` or `coding_tester` covers the grant's whole
unit subtree on **every surface** (worklists, KPI and analytics, sync, the
coder-gate waiver), exactly as a grant on each site in that
subtree would, with no hidden pages. Grants flow down the tree and never up.
Coverage is decided per submission by its routed unit
(`va_submissions.org_unit_id`): a submission with no unit belongs to no
subtree and is reached only through a project or site grant, with one
exception. **The unrouted queue of an organizational project is open to every
`data_manager` of the project, at any scope, unit included**: each sees the
project's unrouted submissions and may route one to a unit inside their own
subtree, never outside it. A `project_site` data manager, whose pair has
no units below it, may route an unrouted case to any unit of the project
(owner decision 2026-10-03, security review 10 #10). The owner accepted the trade-off that a district
data manager sees unrouted cases that may belong to another district
(decision 2026-10-02; implemented in digitva-0wc stage 3). A unit grant
resolves to the forms under its subtree (a form with a submission routed
there, or whose ODK mapping falls back to a unit there), never to its whole
project. Implemented in stage 2 of `digitva-djd`. The
`/api/v1/analytics/dm-kpi/*` panels count the same subtree per submission
(`digitva-m5r`): a row counts when its form's (project, site) pair is in the
manager's project or site scope (never the bare site id, `digitva-lh1h`) or
its submission's unit is in the subtree, tested once, so a mixed manager sees
the union with nothing counted twice. The site-keyed daily aggregates (daily
grid, burndown, backlog trend) count every project at a site, so they serve
only direct sites whose every project with forms there is in the manager's
scope; the rest of the scope is added live from the raw tables, limited to
submissions outside those sites. Coder counts keyed by coder grant project
(utilization, coders per language) include a unit grant's project, but the
coder roster, which names coders, lists only coders whose grant sits inside
the manager's own scope: a project grant's coders of that project at any
scope, a site manager's coders on its own (project, site) pairs, a unit
manager's coders on units in its subtree (owner decision 2026-10-03,
digitva-4b3e). Whole-form
operations need a project or site grant: a form spans several
units, and ODK-side counts cannot be narrowed to one, so a unit-only data
manager refreshes single submissions but neither syncs nor previews a whole
form, and sees other managers' sync runs only on forms a project or site
grant covers. Every other per-submission surface (attachments, workflow
history, the coder and reviewer view pages) checks the submission's own unit,
not only form access.

On a tree project a `coder` or `reviewer` grant at `project` or `project_site`
scope is a grant at the top of the tree: it views every submission of its
project or (project, site) pair, routed or unrouted, and codes or reviews them
unless the project sets a coding scope level with `above_scope_coding_mode =
view_only` (see [Organization Model Policy](organization-model.md), "Coding
scope"; decision 2026-10-02, `digitva-7xq`).

**Mentoring institute members.** A person who belongs to a mentoring institute
(see [Organization Model Policy](organization-model.md), "Mentoring
institutes") may hold only `org_unit` grants of `coder`, `reviewer`,
`coding_tester` or `collaborator_pii`, inside the subtree of a district their
institute is attached to. They may not be given project-, site- or
global-scope grants, nor `interviewer`, `data_manager` or any other role. The
guard applies when a grant is written (create, reactivate, import).

A unit-scoped grant may also carry a `cadre_id`. It is descriptive, and
nothing at runtime consults it, but it is validated on write: the cadre must
be defined at the unit's level, a `coder` grant requires a cadre that may
code at that level, and an `interview_supervisor` grant a cadre that may
supervise interviews there. Cadre rules live in
[Organization Model Policy](organization-model.md).

## Who creates which grants

`admin` creates every grant. The `project_pi` sets up the project and grants
roles in it (see [Organization Model Policy](organization-model.md),
"Spreadsheet setup"). Data managers follow the rule for the project's kind.

### Site projects

Today's rule, unchanged. A `data_manager` creates `coder`, `coding_tester`
and `data_manager` grants at their own scope: a project-scope data manager
at `project` or `project_site` scope in that project, a site-scope data
manager at their own (project, site) pair only. They never create
`admin`, `project_pi`, `site_pi`, `reviewer`, `collaborator`,
`collaborator_pii` or `interviewer` grants. See
[Data-Manager User and Grant Management](dm-user-grant-management.md).

### District (organizational) projects

Decision 2026-10-02; replaces the data-manager role list recorded earlier the
same day. Implemented in digitva-0wc stage 6: every grant write (the
data-manager users page, the admin panel, the project users import) asks
`authz.can_grant`, and the grant lists (the data-manager users page and the
admin panel's grant list for a project PI) are
`authz.grant_list_filter`. A non-admin is refused before the unit and cadre
are validated, so a unit outside their scope, or one that does not exist,
gets the same 403 (digitva-xd1q).

A grant's **subtree** is what it covers: a `project` grant covers the whole
project, a `project_site` grant its (project, site) pair, an `org_unit` grant
its unit and every unit beneath it. "Strictly below" means inside the subtree
but not at the grant's own level: below a `project` grant are its sites and
every unit of its tree; below an `org_unit` grant are its descendant units;
below a `project_site` grant there is nothing.

- `project_pi` creates `data_manager` grants at any level of their project.
- An **In-charge** creates `data_manager` grants at their own level and on
  units beneath it, within their own area (the District in-charge creates the
  District Programme Manager), and the six roles below anywhere in their area,
  as a data manager does.
- A `data_manager` creates:
  - `data_manager` grants only strictly below their own grant, inside their
    own subtree;
  - `interviewer`, `coder`, `reviewer`, `coding_tester`, `collaborator` and
    `collaborator_pii` grants at any level inside their own subtree, their own
    level included.
- The same rule applies to every data manager of a district project, whatever
  the grant's scope. A project-scope data manager's subtree is the whole
  project.
- No data manager creates In-charge, `interview_supervisor`, `site_pi`,
  `project_pi` or `admin` grants, and none grants above or outside their own
  subtree.
- Cadre validation and the mentoring-institute guard apply to every grant
  written this way.

The same powers cover reactivating and revoking those grants, and a data
manager sees, in the grant list, every grant they may manage. Nobody revokes
their own `data_manager` grant from the data-manager page.

## Closed Projects

A project whose `va_project_master.project_status` is not `active` resolves
**no grant of any scope** — `project`, `project_site` or `org_unit` — for any
non-admin role. A closed project is closed for everyone who reached it
through a grant.

- **Grants are not revoked.** Nothing deletes the row or changes its
  `grant_status`. The grant is dormant, not gone: reopening the project
  restores exactly the access that existed before, and the grant's audit
  history is untouched. Closing a project is reversible and must stay so.
- **Admin bypass is unchanged.** `admin` is a `global` grant and is never
  grant-resolved against a project, so an admin still reaches a closed
  project.
- **Redaction uses it too.** `should_redact_pii` counts a PII-granting
  grant only while its project is active, otherwise a dormant grant on a
  closed project would keep personal data visible on an open project's
  screens. It is a decision about personal data and fails open when it
  disagrees with the resolvers.
- **Every resolver uses the shared predicate.**
  `app/services/org_grant_service.py::active_project_condition` is the only
  place this rule is written. Any code that turns grants into access ANDs it
  into its own query — as a correlated `EXISTS`, never a per-grant lookup. A
  new resolver that enumerates grants without it silently reopens the gap,
  which is exactly how the two mechanisms that predated this rule came to
  disagree.

See also [Organization Model Policy](organization-model.md), "Unit-scoped
grants".

## Authorization Rule

A request is allowed only if:

1. the user is authenticated and active
2. the user has the required role for the action
3. the target record falls inside one of the user's explicit grants
4. workflow-specific constraints also pass

Workflow-specific constraints may include:

- allowed language
- workflow state
- allocation ownership
- terminal status checks

These constraints narrow access further, but they do not replace role and scope checks.

Each check runs where the action is performed (the service entry point), so
every route to it, HTML or JSON, enforces the same rule. Starting a recode,
a review, or a reviewer Step 1 / final checks form access and the
submission's coding scope for that role; a recode also requires the caller
to be the coder of the authoritative final, within its window. A write made
in a role's name (coder Step 1, coder not-codeable, reviewer NQA) requires
the caller to hold that role's active allocation for the submission; the
validator of a caller-chosen `action` is not enough.

## Examples

### Example 1

- user role: `coder`
- user grant: `project_site(UNSW01, NC01)`
- submission scope: `project_site(UNSW01, NC01)`

Result:

- allowed to code, if workflow rules also allow it

### Example 2

- user role: `coder`
- user grant: `project_site(UNSW01, NC01)`
- submission scope: `project_site(UNSW01, TR01)`

Result:

- denied, because scope does not match

### Example 3

- user role: `coder`
- user grant: `project(UNSW01)`
- submission scope: `project_site(UNSW01, TR01)`

Result:

- allowed, because the explicit grant covers the whole project

### Example 4

- user role: `site_pi`
- user grants:
  - `project_site(UNSW01, NC01)`
  - `project_site(ICMR01, NC01)`

Result:

- the user may see site `NC01` data in both assigned projects
- the user may not see other sites in those projects unless separately granted

### Example 5

- user role: `data_manager`
- user grant: `project(ICMR01)`

Result:

- the user may browse and view submissions across all sites in `ICMR01`
- the user may mark a submission Not Codeable as a data-management outcome
- the user may not start coding or review
### Example 6

- user role: `project_pi`
- user grant: `project(UNSW01)`

Result:

- the user may see data across all sites in `UNSW01`

## What Is Not A Scope

These must not be the long-term authorization boundary:

- synthetic `va_form_id`
- encoded business identifiers
- ODK project id
- ODK form id

Those values may help resolve context, but they are not the access boundary.

## Grant Storage Baseline

Permission data should be stored as explicit user-role-scope assignments.

Recommended shape:

- `user_id`
- `role`
- `scope_type`
- `project_id`
- `project_site_id`
- `org_unit_id`
- `cadre_id`

Rules (database `scope_shape` CHECK; exactly one target column is set):

- `scope_type = global` is valid only for global roles such as `admin`, and
  leaves every target column empty
- `scope_type = project` requires `project_id`
- `scope_type = project_site` requires `project_site_id` (the
  `va_project_sites` row, which names both project and site) and leaves
  `project_id` NULL; the project is read from the mapping
- `scope_type = org_unit` requires `org_unit_id` and must leave `project_id`
  and `project_site_id` empty; the project is read from the unit
- `cadre_id` is valid only when `scope_type = org_unit`
- a NULL target must not imply project-wide access unless `scope_type = project`
- exactly one active grant per user × role × scope target

This is preferred over loosely structured JSON.

## Migration Rule (historical)

Historical: the form-centric permissions this rule migrated from no longer
exist, and every grant is now an explicit role and scope. Kept as the record
of how legacy access was converted.

The legacy permissions were inconsistent:

- coder and reviewer permissions were form-centric
- Site PI behavior mixed form and site assumptions
- data-manager behavior had to be introduced as explicit scope-based access rather
  than via coder or site-PI shortcuts

Migration policy:

1. resolve each legacy permission to its real project and site
2. map legacy Site PI access into explicit `site_pi` or `project_pi` grants
3. map read-only access into `collaborator` grants where applicable
4. store future access using explicit role and explicit scope type
5. do not carry forward ambiguous permissions

## Implementation Baseline

See [`docs/policy/auth-decorator-rbac.md`](auth-decorator-rbac.md) for the
decorator specification, HTTP status contract, blueprint migration map, and
audit findings addressed.

Implementation should separate:

- role check
- scope check
- workflow state check

They should not remain blended together behind form-id-based helpers.

The scope check is one package, `app/services/authz/` (`can`/`require`,
`scope_filter`, `can_grant`/`grant_list_filter`, `effective_roles`,
`reachable_unit_ids`), the single source for every role and scope decision
in this document. Workflow checks (allocation, state, language, the recode
window) stay with the workflow services. The legacy `permission` JSONB column is kept but never read (digitva-d3y5: production holds only coder and sitepi keys, which were already ignored).

### Every access goes through authz (owner 2026-10-03)

- **No unchecked endpoint.** Every request to the app (web pages, partials,
  JSON APIs, the browser and native app APIs, file and media delivery) is
  decided by `app/services/authz/`. Role gates (`role_required`) read
  `authz.effective_roles`; object and list access use `can`/`require`/
  `scope_filter`. The only exceptions are a reviewed, named public list:
  sign-in, sign-out, password reset and verification links, the app's own
  static assets (CSS, JavaScript, fonts, icons, images shipped with the
  code), health checks and the public landing/help pages. Each entry states
  why. **VA interview attachments are never static and never public**:
  photos, documents, narration audio and any other file belonging to a
  submission are served only through the attachment and media routes,
  which decide with authz (`READ_ATTACHMENTS`) on every request; they must
  not be placed under, or reachable from, the static path or any public
  URL.
- **Fail closed.** A non-public endpoint that completes without consulting
  authz is a defect. Tests probe every registered route with a user holding
  no grants and with each role, and fail if any non-public endpoint skips
  authz. In production such a request is refused (403) and logged, once
  the probe shows no gaps.
- **Redis cache for grant lookups.** A user's resolved grants are cached in
  Redis so every request decides from one fast lookup. The cache is an
  accelerator, never the authority:
  - keyed by user and a per-user version; every grant write, user status
    change, admin flag change and factor/session reset bumps that user's
    version (`authz.invalidate`);
  - a global version is bumped by any change that can alter many users'
    reach: a project, site, project-site or unit activated, deactivated or
    closed, a project's coding-scope settings, the demo-training project
    switch, the organization tree;
  - a short TTL (5 minutes) is the backstop for anything missed;
  - holds grant ids, roles, scopes and project settings only: no personal
    data, no submission data;
  - if Redis is unavailable the grants are read from the database for that
    request (slower, never more permissive); a cached entry that fails to
    parse is discarded.
  - Decisions about one submission (`can`) still read that submission's
    routing from the database; only the grants are cached.

## API And CSRF Baseline

Authorization services should be reusable across server-rendered, HTMX, and React clients.

Rules:

- state-changing browser requests must be served by API-capable routes or thin route handlers that call shared authorization services
- HTMX and React clients must not have separate authorization logic
- browser-originated state-changing requests must enforce CSRF protection, even when the route returns JSON
- the required CSRF header name is `X-CSRFToken`
- GET routes may stay read-only and must not be used as a shortcut for mutation
