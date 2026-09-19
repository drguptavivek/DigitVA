---
title: Access Control Model
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-19
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
- `reviewer`

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

May:

- view data across all assigned sites in an assigned project
- view reporting for an assigned project
- perform oversight actions allowed by workflow policy

### `site_pi`

Site-specific oversight within assigned project-site scope.

May:

- view data for assigned sites within assigned projects
- view reporting for assigned project-site scope
- perform oversight actions allowed by workflow policy

A user may hold `site_pi` grants for many project-site pairs.

### `data_manager`

Data-quality and operational triage role within assigned scope.

May:

- browse all submissions within assigned scope
- open submissions in read-only mode
- document that a submission is not codeable from a data-management perspective
- view reporting and workflow context needed to diagnose submission quality issues

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

Identical to `collaborator` in everything it may do. The only difference is
that personal data is not redacted from what it sees.

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

#### Route wiring (2026-09-19): what a viewer can actually reach

The role and the redaction helper existed before any route granted them —
see `.tasks/viewer-pii-roles.md`. This wired `role_required("collaborator",
"collaborator_pii")` (both spellings gate on the same check,
`VaUsers.is_viewer()`, since the two roles have identical reach) into the
read-only data-management surfaces that go through
`data_management_service.dm_scope_filter` and are already redaction-safe:

- `GET /data-management/` (dashboard), `/data-management/dashboard` (KPI
  shell)
- `GET /api/v1/data-management/submissions`, `/filter-options`, `/kpi`

That is the complete list — five routes.

Deliberately **not** widened, and still `data_manager`/`admin` only:

- every POST/PUT/DELETE in `app/routes/data_management.py` and
  `app/routes/api/data_management.py` (sync, screening, upstream-change
  resolution, org-unit correction, user and grant management) — writes
- `GET /data-management/view/<va_sid>` (submission detail) — renders the
  ~1300-line `renderpartial` route in `app/routes/va_form.py`, which is not
  yet redaction-safe for a viewer (see `.tasks/viewer-pii-roles.md`, "Two
  surfaces still unredacted"); wiring it needs its own change
- `GET /data-management/cod-buckets` (COD bucket reporting) — the page is
  only a shell; every value on it is fetched from
  `app/routes/api/cod_buckets.py` (`/schemes`, `/aggregates`,
  `/export.csv`), all three `data_manager`/`admin` only. Granting the page
  alone would give a viewer a screen that 403s on every fetch. Opening the
  API is a separate widening — `export.csv` emits staff identity with no
  redaction path — so it needs its own review rather than arriving as a
  side effect of granting the page
- `GET /data-management/submissions/<va_sid>/odk-edit` — an edit-adjacent
  affordance (a link into ODK Central's own editor), not a read
- `GET /api/v1/data-management/coder-daily-stats` and
  `/submissions/export.csv` — both emit staff identity (`coder_name`;
  `dm_review_by`/`coder_review_by`/`reviewer_review_by`/`final_assess_by`
  user ids) with no `should_redact_pii` call at all
- `GET /api/v1/data-management/submissions/unrouted` and
  `/project-site-submissions` — each resolves scope through its own private
  helper (`_dm_submission_scope_filter()`, and a direct
  `get_data_manager_projects()`/`get_data_manager_project_sites()` read,
  respectively), not `dm_scope_filter`
- the whole `dm_kpi/*` analytics blueprint and `/api/v1/analytics/*` — these
  resolve scope through `dm_kpi_scope.py` / a separate `_mv_scope_filter`
  helper, not `dm_scope_filter`, and several surface coder/reviewer
  performance data by name with no redaction

`dm_scope_filter` (and the `_dm_scope_pairs` it calls) now resolves
`collaborator`/`collaborator_pii` grants at all three scope types:

- `project` / `project_site` — exactly like `data_manager`, via
  `VaUsers.get_viewer_projects()` / `get_viewer_project_sites()`
- `org_unit` — reuses `org_grant_service.scope_unit_ids_for_roles()` (no
  ltree logic reimplemented) but **bridges the granted unit to its whole
  project** rather than to a site, because a unit does not name one. That
  makes `dm_scope_filter` alone coarser than the grant for an org_unit
  viewer, so it **fails open**: a caller that forgets the question serves
  the whole project. Every caller must therefore decide explicitly.
  `dm_scoped_forms` and `dm_filter_options` carry no personal data, but a
  project's site roster, its ODK project/form ids and its distinct value
  lists are still more than an org_unit grant conveys, so both narrow
  themselves to forms and submissions the user can actually see (an
  `EXISTS` on a visible submission, and a `VaSubmissions` join,
  respectively). A plain `data_manager` never reaches that branch and keeps
  the original queries unchanged. For the two callers that
  enumerate actual submissions (`dm_submissions_page`,
  `_dm_submission_query_parts`, behind the submissions API and the
  dashboard), a second condition
  (`dm_submission_org_unit_condition`) is ANDed in alongside it, restricting
  by `VaSubmissions.org_unit_id`; combined, the net effect is the correct
  grain — visible if inside a direct project/project_site grant, or inside
  the project **and** the submission's own unit is granted.

Inherited, not introduced by this change: neither `_expand_project_ids_to_active_pairs`
nor `get_data_manager_projects()`/`get_viewer_projects()` checks the
**project's own** status (only `va_project_sites.project_site_status` is
checked). A project-scoped grant — `data_manager` or a viewer — on a closed
project still resolves. This was already true for `data_manager` before
this change and is left as is for consistency; it is not this change's
concern to fix.

#### Redaction coverage of the data-management exports

As of 2026-09-19 these surfaces consult `should_redact_pii` and blank staff
identity for a viewer who must not see it:

| Surface | Redacted |
| --- | --- |
| `dm_submissions_page` | `va_data_collector`, `coded_by` |
| `dm_submissions_export_csv` | the `*_by` user ids (`dm_review_by`, `initial_assess_by`, `coder_review_by`, `reviewer_review_by`, `final_assess_by`, `reviewer_final_assess_by`) |
| `dm_coded_cod_snapshot_export_csv` | `coder_name`, `reviewer_name`, `nqa_name`, `social_autopsy_name`, `active_coder_assigned_name`, `active_reviewer_assigned_name` |
| `dm_coder_daily_statistics` | all rows — see below |
| `_dm_search_condition` | the collector, coder and reviewer name clauses |

Two rules the implementations follow, both worth keeping:

- **Empty the column, never drop it.** The submissions export records that
  downstream consumers depend on its column order and offsets, so a redacted
  export has the same shape as an unredacted one.
- **`dm_coder_daily_statistics` returns no rows rather than pseudonymous
  ones.** Every row of that panel *is* staff identity. Blanking the name
  would leave `coder_id` as a stable per-person key across days and across
  exports — the same disclosure by another route.

The three SmartVA exports (`input`, `results`, `likelihoods`) emit no
staff-identity column; the input export's payload already passes through
`_filter_export_payload`.

##### Blocker: `narrative_text` blocks wiring the snapshot export to viewers

**Do not grant `collaborator` the coded-COD snapshot export until
`narrative_text` is resolved.** The staff-identity columns above are handled;
that column is not, and it is the one that carries the deceased's name.

`narrative_text` is the free-text death narrative. It routinely contains the
names of the deceased, the respondent and the attending clinician, in prose,
where no field-level flag reaches them. It is deliberately **not** in
`COD_SNAPSHOT_STAFF_IDENTITY_HEADERS`: it is subject personal data governed by
`is_pii` on the payload field, not staff identity, and filing it under a
staff-identity name would hand the next reader a category error. It is also
not redacted anywhere else — `dm_submissions_export_csv` ships the same
narrative to every role today — so redacting it on one export alone would be
an inconsistent half-change.

The failure this blocker exists to prevent: the staff columns now look
handled, so the export reads as safe to widen, and a plain viewer gets the
deceased's name in free text on the first row.

Resolving it is the `is_pii` decision, applied consistently across both
exports — not this one.

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
- `site_pi` uses `project_site` or `org_unit`
- `data_manager` uses `project`, `project_site` or `org_unit`
- `collaborator` uses `project`, `project_site` or `org_unit`
- `collaborator_pii` uses `project`, `project_site` or `org_unit`
- `coder` uses `project`, `project_site` or `org_unit`
- `coding_tester` uses `project`, `project_site` or `org_unit`
- `reviewer` uses `project`, `project_site` or `org_unit`

A unit-scoped grant may also carry a `cadre_id`. It is descriptive, and
nothing at runtime consults it, but it is validated on write: the cadre must
be defined at the unit's level, and a `coder` grant requires a cadre that may
code at that level. Cadre rules live in
[Organization Model Policy](organization-model.md).

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
- `site_id`
- `org_unit_id`
- `cadre_id`

Rules:

- `scope_type = global` is valid only for global roles such as `admin`
- `scope_type = project` requires `project_id`
- `scope_type = project_site` requires both `project_id` and `site_id`
- `scope_type = org_unit` requires `org_unit_id` and must leave `project_id`
  and `project_site_id` empty; the project is read from the unit
- `cadre_id` is valid only when `scope_type = org_unit`
- `site_id = NULL` must not imply project-wide access unless `scope_type = project`
- exactly one active grant per user × role × scope target

This is preferred over loosely structured JSON.

## Migration Rule

Current permissions are legacy and inconsistent:

- coder and reviewer permissions are currently form-centric
- Site PI behavior mixes form and site assumptions
- data-manager behavior must be introduced as explicit scope-based access rather
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

## API And CSRF Baseline

Authorization services should be reusable across server-rendered, HTMX, and React clients.

Rules:

- state-changing browser requests must be served by API-capable routes or thin route handlers that call shared authorization services
- HTMX and React clients must not have separate authorization logic
- browser-originated state-changing requests must enforce CSRF protection, even when the route returns JSON
- the required CSRF header name is `X-CSRFToken`
- GET routes may stay read-only and must not be used as a shortcut for mutation
