---
title: Submission Analytics Materialized View
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-22
---

# Submission Analytics Materialized Views

## Purpose

DigitVA now provides three focused PostgreSQL materialized views:

- `va_submission_analytics_core_mv`
- `va_submission_analytics_demographics_mv`
- `va_submission_cod_detail_mv`

It also now provides one export/reporting snapshot MV:

- `va_submission_cod_snapshot_mv`

Together they support analytics, trend charts, and reporting queries without
running repeated live joins across operational workflow and coding tables.

The materialized-view layer is:

- one row per `va_sid`
- additive to the current operational schema
- read-only from application code
- refreshed asynchronously

The COD snapshot MV is also:

- one row per `va_sid`
- active/current-state only
- intended for export/reporting rather than KPI counting

## Source Tables

The materialized view reads from:

- `va_submissions`
- `va_forms`
- `va_submission_workflow`
- `va_initial_assessments`
- `va_final_assessments`
- `va_reviewer_final_assessments`
- `va_final_cod_authority`
- `va_smartva_results`

The COD snapshot MV additionally reads from active coding/reporting artifacts,
including:

- `va_narrative_assessments`
- `va_social_autopsy_analyses`
- `va_social_autopsy_analysis_options`
- `va_allocations`
- `map_icd_cod_buckets`
- `map_icd10_legacy_reporting_aliases`
- `mas_cod_bucket_nodes`
- `mas_cod_bucket_schemes`
- `va_submission_payload_versions`

## Included Dimensions

### Project attribution

`project_id` in every analytics MV is the form's own `va_forms.project_id`.
A form is keyed to exactly one `(project_id, site_id)` pair, while a site may
belong to several active projects (`va_project_sites` is unique on the pair,
not on `site_id`), so a submission is never attributed to "the site's
project". Whether a submission is visible is decided by the scope filters,
which compare `(project_id, site_id)` against currently active
`va_project_sites` pairs (`submission_analytics_mv._mv_scope_filter`).
Submissions of a form whose pair has been deactivated therefore drop out of
scoped analytics rather than being re-attributed to another project. A unit
grant (data manager or In-charge) is held to the same rule: a submission
routed into its subtree counts only while its form's pair is active
(`authz.active_pair`), as on the data-management grid. The DM KPI cards
(`DmScope.sql`) and the COD bucket report apply it too.


Across the three views, DigitVA stores:

- project, site, and form identifiers
- submission timestamps and day/week/month buckets
- workflow state
- ODK review state
- ODK sync issue state
- normalized demographic fields
- human coding outputs
- SmartVA outputs

## Core MV — ODK sync state

`va_submission_analytics_core_mv` carries three sync columns:

- `odk_sync_issue_code` — the raw `va_submissions.va_sync_issue_code`
- `has_sync_issue` — true when any sync issue code is set
- `odk_missing` — true when the submission is retired from ODK, i.e. its code
  is `missing_in_odk`

`odk_missing` is never NULL: it is built with `IS NOT DISTINCT FROM`, so a
submission with no sync issue is `false` and `odk_missing = false` keeps it.

Retired rows stay in the MV. Every consumer — the data-manager KPIs and list,
the analytics endpoints, COD bucket reporting and the exports — filters
`odk_missing = false` **by default**, and only the explicit "Missing in ODK"
count and the `odk_sync` filter values `missing_in_odk` / `all` include them.
See [ODK Retired Submissions Policy](../policy/odk-retired-submissions.md).

## Demographics MV

`va_submission_analytics_demographics_mv` includes:

- `va_sid`
- `va_narration_language`
- `sex`
- `analytics_age_normalized_days`
- `analytics_age_band`
- `has_smartva`
- `has_human_initial_cod`
- `has_human_final_cod`

It derives analytics age from sync-time normalized fields already stored on
`va_submissions`:

- `va_deceased_age_normalized_days`
- `va_deceased_age_normalized_years`
- `va_deceased_age_source`

The derivation rules follow the policy in
[WHO 2022 Age Derivation Policy](../policy/who-2022-age-derivation.md).

Important current behavior:

- `analytics_age_normalized_days` is sourced directly from
  `va_submissions.va_deceased_age_normalized_days`
- the winning WHO age source is stored on
  `va_submissions.va_deceased_age_source`
- child and adult ages are normalized using source precedence, not additive
  combination
- raw `age_group` from the XLSForm is not treated as the final analytics age
  band

## Human COD And SmartVA

The view includes:

- latest active initial COD fields
- authoritative final human COD
- parsed human ICD prefixes from stored COD strings
- active SmartVA outputs and ICD codes

Final human COD resolution follows the current authority model:

- reviewer final COD pointed to by `va_final_cod_authority` when present
- otherwise coder final COD pointed to by `va_final_cod_authority`
- fallback to latest active reviewer final COD, then latest active coder final
  assessment, if no authority row is present

## Refresh Model

The materialized view is refreshed by Celery.

Current refresh behavior:

- hourly Celery Beat refresh task
- task name: `app.tasks.sync_tasks.refresh_submission_analytics_mv_task`
- tracked in `va_sync_runs` with `triggered_by = "analytics_mv"`

The refresh helpers are implemented in
[submission_analytics_mv.py](../../app/services/submission_analytics_mv.py).

## Indexes

The materialized views have indexes for common analytics filters, including:

- `va_sid`
- `submission_date`
- `(project_id, site_id)`
- `workflow_state`
- `odk_review_state`
- `analytics_age_band`
- `sex`
- `final_icd`
- `smartva_cause1_icd`

## Current Intended Consumers

The materialized view is intended for:

- reporting endpoints
- dashboard analytics APIs
- future project/site trend visualizations
- SmartVA versus human-COD comparison analysis

### Area dashboard

`GET /area/` (page) and `GET /api/v1/area/projects`,
`/api/v1/area/summary?project=&unit=&site=&period=&format=` and
`/api/v1/area/staff` (JSON) show deaths, interviews and coding for the part
of a project a user holds a grant for (`docs/policy/area-dashboard.md`,
beads `digitva-stc`, `digitva-qfh8`). Code:
`app/services/area_dashboard_service.py`, `app/routes/area.py`,
`app/routes/api/area.py`.

- Gated by `login_required`: any active grant of any role opens an area; no
  grant gives an empty project list. The navbar link shows for any user with
  an active grant (`VaUsers.has_any_active_grant`). Expo web opens the same
  page ("Statistics", Mentoring screen).
- Scope is viewing scope, a union over all roles, per project. A project with
  an active organization level is a tree project and uses
  `authz.reachable_unit_ids` (whole tree for admin, the project's
  PI, or any project- or site-scoped grant; otherwise unit-grant subtrees),
  shared with the organization API's unit picker. A project with no tree is
  shown per site: all active sites for admin, PI or a project grant, else the
  granted sites. A project, unit or site outside scope is a 404.
- `period` is `30d`, `90d`, `12m` or `all` (default); anything else is a 400.
  `period_start` is UTC midnight that many days back, so it equals the data
  manager's `date_from`. It filters deaths reported (case `created_at`),
  submitted (`submission_at`) and causes (date of death); nothing else.
- Rows are the grant roots (or the project's top-level units when the scope
  is project-wide, plus an "Unrouted" row), or the direct children of a
  selected unit. Each row is its whole subtree, counted once. Every row and
  the card carry `COUNT_KEYS`, from four grouped queries per level:
  - snapshot (`get_dm_org_unit_stats_from_mv(include_breakdown=True,
    since=...)`, sites `get_area_site_stats_from_mv`, unrouted
    `get_area_unrouted_stats_from_mv`): `submitted` in the period and the
    `awaiting_coding` and `not_codeable` coding buckets;
  - case counts over `va_death_register` (`_case_count_columns`, duplicates
    and cancelled cases out): `deaths_reported` in the period,
    `deaths_7_days`, `deaths_30_days`, `interviews_pending` (status in
    `user_home_service.OPEN_CASE_STATES`) and `pending_over_7_days` /
    `_30_days` by `created_at`;
  - live counts over one `_live_flags` subquery of `va_submissions`
    (retired, confirmed-duplicate and inactive-pair submissions out):
    `final_cod` (an authority row naming a coder or reviewer assessment),
    `smartva_failed` (active `va_smartva_results` row with outcome
    `failed`, via `ix_va_smartva_results_sid_status_covering`) and
    `visit_notes`.
  Unit rows join on ltree `<@`; there is no query per unit.
- Card (`card`, every level): the selected unit's own subtree row (the unit
  rides along in its children's grouped queries), else the sum of the
  non-overlapping rows. Plus `medians` (one query over the core MV joined to
  `va_death_register` on `va_sid`, index `ix_va_death_register_va_sid`, and
  `va_final_cod_authority`; `percentile_cont`, all time) and `causes`
  (`cod_bucket_mapping_service.count_coded_submissions_by_cause` on the
  default reporting scheme, then `suppress_causes`: hidden under 20 coded,
  causes under 5 and past the top ten folded into "Other (suppressed)").
- `project_card` (project root, project-wide scope only): `stations` from
  `project_stations`, active devices with a station config, their latest
  bundle (`va_bundle_ingests`), never-synced count. One query.
- `format=csv`: `summary_csv`, long format (section, area code, area name,
  measure, value), aggregates only; text cells starting `= + - @` get a
  leading `'`.
- Freshness: the snapshot label is the `finished_at` of the latest successful
  `analytics_mv` run in `va_sync_runs`. Ad-hoc refreshes from the data
  manager and analytics screens are not recorded there, so the label is a
  lower bound. Both labels are formatted in the user's timezone.
- Links (`links` on the card, sites-mode rows and unit rows' visit notes,
  count key -> URL): `link_screens` offers a screen only when the user holds
  that role on the project and passes the target route's own role gate.
  Data manager, collaborator or collaborator_pii or admin: `/data-management/`
  with every URL filter it reads, blank unless set (project; `site`,
  `org_unit` or `date_from` where the count is exactly that filter; no
  data-manager link at a root of several grant roots). Coder: `/coding/` on
  awaiting coding. Interviewer (without data manager): `/intake/` on
  submitted.
- Staff view (`GET /api/v1/area/staff?project=&unit=&site=`,
  `area_dashboard_service.area_staff`, bead `digitva-stc.2`): interviewers
  only since 2026-10-22 (the per-coder table was cut). Area as the summary's
  (`_in_area`); a root that is not project-wide, and anything outside scope,
  is a 404. One query over `va_death_register` (registered, started), one
  over `va_web_intake_drafts` by owner (submitted, in progress), one over
  `map_case_contact_attempts` in the last 30 days. Confirmed duplicates
  excluded. At most 500 rows (`truncated`). When `should_redact_pii` hides
  staff identity the queries do not run and the response is
  `staff_identity_redacted: true` with no rows.

Not all existing dashboard endpoints have been migrated to use the view yet.
Some current operational dashboard queries still read directly from live tables.
The analytics MV itself is now reviewer-authority-aware; remaining legacy
reporting cleanup is outside the view.

## COD Snapshot MV

`va_submission_cod_snapshot_mv` centralizes the active COD-facing reporting
state for a submission. It includes:

- latest coder Step 1 data preserved across final COD submission
- latest active coder final COD data
- latest active reviewer final COD data
- authoritative final COD data
- active SmartVA causes and ICDs
- `WHO_2022_VA_2026` bucket mapping for coder, reviewer, authoritative, and
  SmartVA CODs (migration `d1a6e3b7c2f4`; before it, `WHO_2022_VA`, ICD-10
  only)
  - each value is bucketed through the rows of its own classification, which
    its code shape decides: ICD-10 values through the `icd10` rows, ICD-11
    values through the `icd11` rows (exact code, then the nearest ancestor on
    the `mas_icd11_mms` parent chain; a post-coordinated value by its first
    stem). SmartVA ICDs are ICD-10. There is no crosswalk
  - each bucket has a `*_who_bucket_provenance` column: `icd10`,
    `icd11_native`, `unmapped` (a value with no bucket), or NULL (no value)
  - ICD-10 lookup is alias-aware for historical ICDs through
    `map_icd10_legacy_reporting_aliases`
  - the MV keeps the raw ICD fields unchanged and uses the alias only for
    reporting-bucket assignment. `*_icd` columns stay ICD-10 only; an ICD-11
    code is in the `*_cod_text` column
  - `build_submission_cod_snapshot_mv_sql()` still returns the old SQL by
    default, for the historical migrations that call it;
    `icd11_buckets=True` returns the current SQL
- active NQA projection, including individual NQA question columns
- active Social Autopsy projection, including analysis summary fields and raw
  active-payload `sa*` questionnaire fields
- active coder/reviewer assignment names where available

The snapshot MV is intended for the coded COD export surface and similar
submission-level reporting workloads. It is not a history store.

## Verification

The materialized-view behavior is covered by focused tests in:

- [test_submission_analytics_mv.py](../../tests/services/test_submission_analytics_mv.py)

The tested cases include:

- same-day neonatal deaths with hour-level age
- child normalization from `ageInDays`
- authoritative final human COD selection
- reviewer final COD precedence over coder final COD in analytics output
- ICD parsing for human and SmartVA outputs
