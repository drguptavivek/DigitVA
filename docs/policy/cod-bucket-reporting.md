---
title: COD Bucket Reporting Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-21
---

# COD Bucket Reporting Policy

## Purpose

Define how DigitVA classifies coded submissions into reporting-oriented
cause-of-death buckets such as `SRS India` and `CMEA10`.

This policy also defines who may access the CoD dashboard and how reported
data must be scoped.

## Policy

1. Authoritative coding data remains the submission's final ICD outcome.
2. Reporting bucket classification is a separate, versioned mapping layer.
3. Changing a bucket mapping scheme must not mutate coder or reviewer final COD
   records on submissions.
4. Multiple reporting schemes may coexist.
5. A scheme may define different hierarchy depth and age-scoped trees.
6. Deleting a bucket node must never mutate authoritative submission COD rows.
7. When deleting a bucket node, the operator must choose one of:
   - unmap all affected ICD codes
   - move all affected ICD codes to an `Unmapped` replacement leaf
8. Deleting a non-leaf bucket cascades to all descendant bucket nodes.
9. If the operator chooses `move_to_unmapped` for a non-leaf delete, DigitVA
   must create an `Unmapped` replacement chain in place of the deleted branch
   and move all affected ICD mappings to the replacement leaf.
10. The admin COD bucket panel must support JSON export per scheme.
11. Scheme export must include the scheme metadata, all age bands, all hierarchy
    nodes, and all ICD mappings for that scheme.
12. The ICD picker used while maintaining COD bucket mappings must read from
    `mas_icd10_2019_2`, not legacy `va_icd_codes`.
13. The COD bucket ICD picker must return active three-character or detailed
    ICD rows from the master table, without applying age- or sex-based
    filtering. Rows that are not currently assignable in coding must still be
    available for COD bucket mapping and must be explicitly marked as
    `Currently not assignable in coding`.
14. The admin COD bucket editor must expose a scheme-level grid of active
    three-character or detailed ICD rows that are not mapped anywhere in the
    current scheme, across all age groups, shown as a single ICD code list
    rather than split three-character vs detailed columns.
15. Rows in that scheme-level unmapped ICD grid that are not currently
    assignable in coding must remain bulk-mappable and must be explicitly
    marked as `Currently not assignable in coding`.
16. The scheme-level unmapped ICD grid must support bulk allocation by letting
    the operator choose a target age band and a target disease-level leaf
    within that scheme, then map multiple selected ICD codes in one action.

## CoD Dashboard Access Policy

The CoD dashboard is a reporting surface. Access must follow the same
route-level role checks and grant-scoped authorization model used elsewhere in
DigitVA.

DigitVA does not use a separate policy class of "operational" versus
"read-only oversight" roles. Each route defines which roles are allowed, and
scope is then limited by that user's explicit grants.

Initial access baseline:

- `admin` may access all CoD dashboard pages and APIs globally
- `data_manager` may access the CoD dashboard within their explicit grant scope
- `project_pi` should have CoD dashboard access within granted projects
- `site_pi` should have CoD dashboard access within granted project-site pairs
- `collaborator` should have CoD dashboard access within explicit collaborator
  scope when that role is fully wired into route authorization

Initial non-access baseline:

- `coder` must not receive CoD dashboard access by default
- `reviewer` must not receive CoD dashboard access by default

Rationale:

- the existing `/data-management` area is already the operational home for
  scoped reporting and triage
- the application already defines access at the route level per role
- `admin` already owns global visibility and scheme maintenance
- `data_manager`, `project_pi`, `site_pi`, and `collaborator` are valid
  reporting consumers when the route explicitly allows them

Implementation rule:

- scheme maintenance remains admin-only
- do not infer CoD dashboard access from generic read access elsewhere without
  explicit route and API authorization
- if a route grants a role access to the CoD dashboard, that route must still
  enforce the same scoped project/project-site visibility rules for that user

## CoD Dashboard Scope Policy

The CoD dashboard must remain scope-based, following the same explicit grant
boundaries as other data-management reporting.

Scope rules:

- `admin` sees all projects, sites, forms, and coded submissions
- project-scoped `data_manager` grants see all active project-site pairs in the
  granted project
- project-site-scoped `data_manager` grants see only that explicit
  project-site pair
- `project_pi` sees all active project-site pairs in granted projects
- `site_pi` sees only explicitly granted project-site pairs
- `collaborator` follows the same explicit project or project-site scope model
  as documented in the access-control policy

Data must be filtered by active `(project_id, site_id)` scope pairs, not by
free-floating project, site, or form filters alone.

Form behavior:

- form filters are convenience filters inside the user's allowed scope
- a form must never expand visibility beyond the user's scoped
  project-site pairs
- inactive or de-scoped project-site mappings must not continue to leak into
  CoD dashboard visibility

Aggregation boundary:

- CoD counts must be computed only from coded submissions whose resolved
  project-site pair is inside the user's allowed scope
- the dashboard must not collapse across out-of-scope rows and then filter only
  the presentation layer

Single-project-first rule:

- the product remains single-project-first unless a task explicitly broadens
  that behavior
- for the initial rollout, the default user journey should assume one active
  project context with optional site/form narrowing inside that project
- multi-project comparison can remain an admin capability or a later expansion,
  but it should not drive the first-pass UX

## Data Included In Scope

Within the authorized scope, the CoD dashboard may report only authoritative,
reporting-safe COD aggregates and supporting filters.

Included baseline:

- authoritative final ICD-derived bucket counts
- age-scope splits defined by the selected reporting scheme
- selected filter dimensions already used in data-management reporting, such as
  project, site, form, and submission date
- unmatched-ICD counts and drill-downs for the same in-scope population

Excluded baseline:

- draft coder decisions
- reviewer work-in-progress rows
- submissions outside the caller's explicit project/project-site scope
- raw payload data unless another policy explicitly adds a drill-down use case

## Export And Drill-Down Policy

If the CoD dashboard exposes export or drill-down behavior:

- the same scope rules as the dashboard page must apply
- the same current filters must apply
- exports should default to aggregate outputs, not row-level submission dumps
- any row-level drill-down must be explicitly justified and documented because
  it increases sensitivity beyond the current aggregate view

For the initial rollout, prefer:

- aggregate tables
- aggregate chart downloads
- unmatched ICD summaries

Avoid introducing submission-level CoD dashboard drill-down until there is a
clear operational need and a separate policy baseline for who may inspect those
rows.

## Scheme model

DigitVA stores reporting schemes as master data:

- `mas_cod_bucket_schemes`
- `mas_cod_bucket_nodes`
- `map_icd_cod_buckets`

Supported examples:

- `SRS India`
- `CMEA10`

## Age scope policy

Age scope belongs to the reporting mapping, not to the submission's coded ICD
record.

Current SRS scopes:

- `adult_over5y`
- `child_1_59m`
- `neonate`

Current CMEA10 scope:

- no age scope

Age band bounds are interpreted as:

- lower bound: inclusive (`>=`)
- upper bound: exclusive (`<`)
- every stored age band must have explicit lower and upper bounds
- DigitVA must not persist open-ended `NULL` age ranges for COD schemes
- built-in open-ended schemes use an explicit upper cap of `120 years`

Age band normalization for COD reporting uses these fixed conversions:

- `days` -> `1 day`
- `months` -> `365 / 12 days`
- `years` -> `365 days`

Because month-to-day conversion is approximate, age-band overlap and gap checks
in the admin creator are operator feedback, not hard blockers.

## Aggregation policy

Bucketed COD aggregation must be driven from authoritative final ICD outcomes,
not from draft or non-authoritative coding rows.

Current aggregate inputs:

- authoritative `final_icd`
- demographics-derived age band
- active COD bucket mapping scheme
- per-age-group count of final ICDs that do not match any active scheme category

Unmatched final ICDs must not be merged into hierarchy rows. The reporting UI
must show them as a note for the relevant age group stating that those
submitted CODs did not match any category and were dropped from the displayed
table. That note must offer a modal tabulation of the dropped ICD codes for the
selected age group, split into:

- ICD codes not included in the selected scheme's CoD categories for that age group
- ICD codes not eligible for coding

## Change policy

If the group, sub-group, or leaf bucket for an ICD code changes:

- update the mapping scheme version
- refresh aggregate outputs
- do not rewrite historical submission COD rows

This preserves auditability and keeps coding and reporting concerns separate.

## Deletion policy

COD bucket node deletion affects only reporting taxonomy master data:

- `mas_cod_bucket_nodes`
- `map_icd_cod_buckets`

It must not rewrite any submission coding records.

Deletion behavior is:

- leaf delete + `unmap`
  - delete the leaf
  - delete associated ICD mappings
- leaf delete + `move_to_unmapped`
  - delete the leaf
  - create or reuse an `Unmapped` replacement leaf under the same parent
  - move associated ICD mappings there
- higher-level delete + `unmap`
  - delete the selected node and all descendants
  - delete all ICD mappings from descendant leaves
- higher-level delete + `move_to_unmapped`
  - delete the selected node and all descendants
  - create or reuse an `Unmapped` replacement branch in the same parent
    position
  - move all descendant ICD mappings to the replacement leaf
