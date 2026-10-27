# digitva-0hul: KPI query refresh (draft, not implemented)

Status: plan for owner review. Nothing here is implemented; no app code, test,
migration or config was edited. Every dev number below came from read-only
SELECT / EXPLAIN (10 s statement timeout) against the shared dev Postgres on
2026-10-27. Counts only; no personal data was printed.

## 0. How to read this

**Scope A (dev comparison scope).** What `testadmin` (admin) sees through
`dm_scope()`: every active `(project, site)` pair of every project except the
training project TRN01 (`dm_grant_scope` -> `_without_training`), submissions
still in ODK (`va_sync_issue_code IS DISTINCT FROM 'missing_in_odk'`), no
confirmed duplicates (dev has none: `va_death_register.status='duplicate'` is
0 rows, so the duplicate predicate changes nothing on dev). Scope A =
**7,811 submissions** (8 of them web intake, `va_forms.form_source='web'`).
Its states: reviewer_eligible 7,062; coder_finalized 451; ready_for_coding 193;
attachment_sync_pending 77; consent_refused 22; not_codeable_by_coder 3;
reviewer_finalized 2; not_codeable_by_data_manager 1.

**Dev data caveats.**
- All in-scope projects have `recode_window_minutes = 1440`, so the hard-coded
  24 h agrees with the setting on dev; the defect is real but invisible here
  (only TRN01 has 60).
- The only organization-mode projects with data (TST001, GUJ026, HP2026,
  DEMO01) hold 1-3 submissions each, so unit-scoped differences are shown on
  the coder-grant side (TST001 has 10 units, 5 coders) and otherwise argued
  from the code. Org-unit numbers are a **gap in the dev dataset**.
- `va_daily_kpi_aggregates` on dev stops at 2026-05-11 (122 rows, 11 sites).
  See issue S2: nothing schedules the snapshot task.

**Reference implementations to align to** (already current, 2026-10-23/24):
`app/services/area_dashboard_service.py` (coding buckets from
`WORKFLOW_CODING_BUCKETS`, training excluded, duplicates excluded, per-unit
rollups via `get_dm_org_unit_stats_from_mv` / `area_breakdown_columns`) and
`app/services/sitepi_reporting_service.py` (pair-keyed, unit-subtree,
authority-aware).

**Level / unit grants / peer columns (coordinator request).**
- *Level*: the level the KPI belongs at. P = project (Tier 1, non-PII,
  aggregate), D = district (Tier 3 in-system, PII-capable), U = facility
  unit (CHC / PHC / SC), S = system (ODK sync, SmartVA queue; not per unit).
- *Follows unit grants*: does the query count the subtree a unit grant covers
  (`DmScope.sql()` subtree branch)? Y = yes today; N = counts a wider set
  than the grant; n/a = system level.
- *Peer*: should it be compared across peer units at the same level (districts
  of a state, PHCs of a CHC, sibling sites)? Y/N. Peer comparison needs the
  per-unit slice that only the area dashboard has today; no DM KPI endpoint
  groups by unit (see S5b).

## 1. Inventory and status

63 KPI outputs counted (table rows below): 48 policy KPI ids in
`app/routes/api/dm_kpi/*` (the daily grid split into its four column groups),
4 stored-aggregate groups, 5 `analytics.py` outputs, the MV matrix helpers,
the Site-PI service (3 entry points) and the 3 role dashboards. **Stale: 27.**
OK: 36 (7 of them with a minor note). "Last changed" is `git log -1 --format=%cs` of the
file.

Dev columns: *cur* = what the code returns now on Scope A; *fix* = the
corrected query on the same scope. "same" = identical on dev (defect latent).

### 1a. Daily grid and stored aggregates

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix (dev) | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 1 | C-01 Daily grid, Total column | `dm_kpi_grid.py:235` (live-fill), `:53` | 2026-10-24 | **stale** S1 | Live-filled days (today, any gap, and every day when aggregates are old) set `total` = *created that day*, not cumulative as the aggregate path does (`:275`, from `SUM(total_submissions)`). | Total today: **0 -> 7,811** | P, D | Y (live) | N |
| 2 | C-01 Pending column | `dm_kpi_grid.py:161-181`, `:239` | 2026-10-24 | **stale** S1/S5 | Live pending = 3 states; stored `pending_count` = 6 states (`kpi_tasks.py:330`); past live-filled days show 0. | **193 -> 270** | P, D, U | Y | Y |
| 3 | C-01 Coded column | `dm_kpi_grid.py:120` | 2026-10-24 | **stale** S6 | Counts demo-session finalizations (SADEMO is `demo_training_enabled`) as output. | cumulative events **7,450 -> 6,877** | P, D | Y | Y |
| 4 | C-01 New / Updated / Not analysable / Not codeable | `dm_kpi_grid.py:132-157` | 2026-10-24 | OK-note | Event/created counts, retired + duplicate filtered. New counts web intake too (column still named "New from ODK", policy says sync_runs.records_added). Label only. | same | P, D | Y | N |
| 5 | Stored: total / new / updated | `kpi_tasks.py:263-310` | 2026-10-11 | **stale** S2 | Site-keyed (not project/unit keyed), mixes web + ODK, `project_id` = latest owner only, and a stored day is never recounted when forms are retired later (MH01 holds 63 retired KEM001 forms and 59 ROOT01 forms). | MH01 2026-05-11: stored 118 vs 59 recounted today | P | N (site only) | N |
| 6 | Stored: coded / reviewer / reopened / consent / not-codeable events | `kpi_tasks.py:312-440` | 2026-10-11 | **stale** S6 | No demo / tester exclusion; event counts. | as row 3 | P, D | N | Y |
| 7 | Stored: pending_count, upstream_changed_count (end of day) | `kpi_tasks.py:330,404`, `:165` | 2026-10-11 | **stale** S2 | Current state stamped on the snapshot date, not history; backlog_trend reads it as history. 6-state pending vs 3-state live. | n/a (history) | P, D | N | Y |
| 8 | Stored: coding_duration min/max/p50/p90 | `kpi_tasks.py:442-483` | 2026-10-11 | **stale** S3 | Same fan-out join as C-08 (`:459`). | see C-08 | P | N | Y |
| - | Scheduling | `kpi_tasks.py:35`; no row in `celery_periodictask`, no `ensure_*_scheduled`, no caller in `sync_tasks.py` | - | **stale** S2 | Policy says daily + after each sync; neither exists. `tz = "UTC"` (`:190`) is unused; `daily_kpi_aggregation_timezone` is not implemented anywhere. | aggregates end 2026-05-11 | - | - | - |

### 1b. Sync (system level)

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 9 | C-02 Last sync run | `dm_kpi_sync.py:72` | 2026-10-05 | OK | `va_sync_runs`, direct grants only (digitva-38lp). | - | S | n/a (refused for unit-only) | N |
| 10 | C-03 Sync error rate | `dm_kpi_sync.py:72` | 2026-10-05 | OK | idem. | - | S | n/a | N |
| 11 | C-13 Sync latency | `dm_kpi_sync.py:165` | 2026-10-05 | **stale** S11 | Includes web intake rows (5 on dev, p50 0 s): not an ODK->app latency. | n 7,808 -> 7,803 (odk only) | S/P | Y | N |
| 12 | C-14 Attachment health | `dm_kpi_sync.py:232` | 2026-10-05 | **stale** S11 | Web intake has no ODK attachments; counted as "missing". | missing **9/7,734 -> 1/7,726** (0.12% -> 0.01%) | P, D | Y | Y |
| 13 | D-SH-01 Attachment completeness | `dm_kpi_sync.py:232` | 2026-10-05 | OK-note | Uses `attachment_forms_total`; policy text says downloaded+skipped+errors (doc drift, not a defect). | - | S | n/a | N |
| 14 | D-SH-04 SmartVA failure rate | `dm_kpi_sync.py:329` | 2026-10-05 | OK | `va_smartva_runs`, system level. | - | S | n/a | N |

### 1c. Pipeline

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 15 | C-04 % uncoded | `dm_kpi_pipeline.py:61` | 2026-10-24 | OK | 6 states = awaiting_coding + in_coding buckets; this is the reference definition. Pool = not refused / not DM-NC (policy). | 270 / 7,788 = 3.5% | P, D, U | Y | **Y** |
| 16 | C-07 Aging | `dm_kpi_pipeline.py:109` | 2026-10-24 | OK | ready_for_coding only, by design. >48 h 191, >30 d 172. | - | D, U | Y | Y |
| 17 | C-08 Time to code | `dm_kpi_pipeline.py:152` (join `:189-192`) | 2026-10-24 | **stale** S3 | `e2 JOIN e1 ON same va_sid AND e1='coding_started'` pairs every finalization with every start, past and future; a recoded case counts twice; `recode_started` ignored; demo guard is per submission. | pairs **7,180 -> 6,877**; min **-24,063 s -> 0 s**; max **2,477,175 s -> 4,121 s**; p50 155 s -> 149 s | D, U | Y | Y (median per unit, min-n) |
| 18 | C-09 % reviewed | `dm_kpi_pipeline.py:224` (`:263`) | 2026-10-24 | **stale** S10 | 24 h hard-coded; project window is `recode_window_minutes`. Eligible set otherwise right. | 2/7,088 = 0.03% -> same | P, D | Y | Y |
| 19 | C-10 Upstream queue | `dm_kpi_pipeline.py:294` | 2026-10-24 | OK | ODK vs send-back split via `revision_request_sql`. 0 on dev. | - | D, U | Y | Y |
| 20 | C-11 % with upstream | `dm_kpi_pipeline.py:294` | 2026-10-24 | OK | idem. | - | D, U | Y | Y |
| 21 | D-WT-02 Upstream resolution time | `dm_kpi_pipeline.py:294` | 2026-10-24 | OK | - | - | D | Y | N |
| 22 | D-WT-04 Reopen rate | `dm_kpi_pipeline.py:294` | 2026-10-24 | OK-note | Denominator counts `coder_finalized` only (not `recode_finalized`); defensible. Counts demo events (S6) but reopens do not occur in demo. | - | P, D | Y | Y |
| 23 | C-19 Inflow vs outflow | `dm_kpi_pipeline.py:456` | 2026-10-24 | **stale** S7 | Inflow = `smartva_completed` only; cases also enter the pool via `smartva_failed_recorded`, resets and admin override (120 of 193 current ready_for_coding have no smartva_completed). Outflow has the demo problem (S6). | inflow cum **6,923 -> 7,107** (+184 failed-SmartVA entries; 90 d: 41 -> 44) | P, D | Y | Y |
| 24 | C-22 Site bottleneck | `dm_kpi_pipeline.py:527` (`:546-563`) | 2026-10-24 | **stale** S5/S5b | Pending = 3 states (C-04 uses 6); groups by `site_id` only (an organization project has one automatic site, so it returns one row); no unit slice. | MH01 **33.6% (39/116) -> 100% (116/116)**; rank ~6 -> 1 (tied with NC02, Z001, O002); all 77 attachment_sync_pending in scope sit at MH01, hence the full swing | D, U | Y | **Y: this is the peer KPI** |
| 25 | D-WT-01 Reviewer throughput | `dm_kpi_pipeline.py:589` | 2026-10-24 | OK | - | - | P, D | Y | Y |
| 26 | D-WT-03 Backlog trend | `dm_kpi_pipeline.py:634`, `:709` | 2026-10-24 | **stale** S5/S2 | Stored series = 6 states (history frozen), live "today" and outside-aggregates add = ready_for_coding only: the line mixes two quantities. | 193 vs 270 | P, D | Y (live part) | Y |

### 1d. Exclusions

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 27 | C-05 % not codeable | `dm_kpi_exclusions.py:60` | 2026-10-05 | OK | 4 / 7,811 = 0.05%. | - | P, D | Y | Y |
| 28 | C-06 Not analysable rate (+ by reason) | `dm_kpi_exclusions.py:60` | 2026-10-05 | OK | consent_refused state incl. web outcomes; 22 / 7,811. | - | P, D, U | Y | Y |
| 29 | D-QG-01 Coder not-codeable rate | `dm_kpi_exclusions.py:60` | 2026-10-05 | OK | 3 / 7,788. | - | D, U | Y | Y |
| 30 | D-QG-02 DM not-codeable rate | `dm_kpi_exclusions.py:60` | 2026-10-05 | OK | 1 / 7,811. | - | D | Y | Y |
| 31 | D-QG-03 Exclusions by actor | `dm_kpi_exclusions.py:173` | 2026-10-05 | OK-note | Active review rows; 3 coder, 1 DM, all still in the matching state on dev. Reviewer-rejection item in policy is not implemented (policy drift). | - | P, D | Y | N |
| 32 | D-QG-04 Coder NC reasons | `dm_kpi_exclusions.py:173` | 2026-10-05 | OK | - | - | D | Y | N |
| 33 | D-QG-05 DM NC reasons | `dm_kpi_exclusions.py:173` | 2026-10-05 | OK | - | - | D | Y | N |
| 34 | C-23 Blocked forms | `dm_kpi_exclusions.py:294` (`:372-440`) | 2026-10-05 | **stale** S4 | Scope is the coding pool, but "ODK flagged", "missing language" and `total_blocked` also count already-coded cases (reviewer_eligible etc.), which are not blocked. | total_blocked **145 -> 81**; ODK flagged **71 -> 4** | D, U | Y | Y |
| 35 | D-QG-06 ODK has issues | `dm_kpi_exclusions.py:540` | 2026-10-05 | OK | Population-wide by definition; 72 / 7,811. | - | P, D | Y | Y |
| 36 | D-QG-07 NQA completion | `dm_kpi_exclusions.py:447` (`:484-491`) | 2026-10-05 | **stale** S12 | Joins the project via "any active project at the form's site, LIMIT 1", not the form's own project (docs: "analytics never re-attributes"). | same on dev (MH01 coded rows are all KEM001 for both flags); wrong when a shared site's two projects differ (MH01: KEM001 vs KEMDEM have different `social_autopsy_enabled`) | P | Y | N |
| 37 | D-QG-08 SA completion | `dm_kpi_exclusions.py:447` | 2026-10-05 | **stale** S12 | idem. | same | P | Y | N |

### 1e. Workflow

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 38 | D-WF-01 CONSORT flowchart | `dm_kpi_workflow.py:217`, split `:184-214` | 2026-10-05 | **stale** S10 | within/beyond "24h" hard-coded. Label "Consent Refused" (`STATE_LABELS`) predates "Not analysable". | beyond 451 -> same on dev | P, D | Y | N |
| 39 | D-WF-02 State velocity | `dm_kpi_workflow.py:309` | 2026-10-05 | OK | Tester events excluded (ggc3); demo not (S6, minor). | - | S/P | Y | N |
| 40 | D-WF-03 Stagnation | `dm_kpi_workflow.py:416`, thresholds `:129-141`, `:439` | 2026-10-05 | **stale** S10 | coder_finalized 24 h window hard-coded in thresholds, SQL and DM_ACTIONS text. 451 coder_finalized are older than 24 h on dev (reviewer promotion lag, not a KPI defect). | same on dev | D, U | Y | Y |
| 41 | D-WF-04 Daily transitions | `dm_kpi_workflow.py:532` | 2026-10-05 | OK | Tester events excluded. | - | P | Y | N |

### 1f. Coders and language

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 42 | C-21 Coder utilization | `dm_kpi_coders.py:55` (`:78-86`) | 2026-10-03 | **stale** S9 | Denominator = every active coder grant of the project(s), including coders whose unit grant lies outside the DM's subtree. | TST001, DM at PHC01: **5 -> 4** coders that cover the subtree (1 if limited to grants inside it, the roster rule) | D, U | **N** | Y |
| 43 | C-12 Coder throughput | `dm_kpi_coders.py:129` | 2026-10-03 | OK | Reads active `va_final_assessments` (tester finals are deactive); excludes `is_tester` by status. Demo finals are deactive (`demo_expires_at`). | - | D | Y | Y |
| 44 | C-24 Forms per coder by language | `dm_kpi_coders.py:129` | 2026-10-03 | OK | idem. | - | D | Y | N |
| 45 | D-LC-04 Coder output by language | `dm_kpi_coders.py:129` | 2026-10-03 | OK | idem. | - | D | Y | N |
| 46 | D-LC-06 Coder roster | `dm_kpi_coders.py:229` | 2026-10-03 | OK | Already scoped by `grant_in_scope_sql` (owner 2026-10-03). | - | D | Y | N |
| 47 | D-QG-09 Coder-reviewer disagreement | `dm_kpi_coders.py:318` (`:340`) | 2026-10-03 | **stale** S8 | Compares `va_conclusive_cod` text, not the WHO 2026 bucket / ICD-11 primary stem, and ignores `va_final_cod_authority`. | 3 pairs: raw **2/3 (67%) -> bucket 1/3 (33%)**; ICD-10 code 0/3 | P, D | Y | N |
| 48 | C-15 Language gap alert | `dm_kpi_language.py:58` (`:90`, `:100-117`) | 2026-10-03 | **stale** S9 | Coder language match is case-sensitive exact; allocation matches `lower(trim())` (`coder_workflow_service.py:105-110`) and treats a coder with no languages as "any". Coders counted project-wide, not for the unit subtree. | "English" (1 case): coders **0 -> 98**, flagged as a gap -> not a gap | P, D | N (coders) / Y (cases) | N |
| 49 | C-20 Language with max pendency | `dm_kpi_language.py:58` | 2026-10-03 | OK-note | 3-state "ready pool" by policy. With attachment_sync_pending marathi would read 113 not 38; decide whether "pendency" means the pool or the pipeline (open question Q2). | - | D | Y | Y |
| 50 | D-LC-03 Language gap analysis | `dm_kpi_language.py:58` | 2026-10-03 | **stale** S9 | as C-15. | as C-15 | P, D | N | N |
| 51 | D-LC-01 Language distribution | `dm_kpi_language.py:187` | 2026-10-03 | OK-note | "English"/"english" are separate groups. Group by `lower(trim())` (cosmetic). | english 606 + English 1 | P | Y | N |
| 52 | D-LC-07 Missing / unmapped language | `dm_kpi_language.py:263` | 2026-10-03 | OK | - | - | D | Y | Y |

### 1g. Burndown

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 53 | C-16 Mean daily coding rate | `dm_kpi_burndown.py:59` (`:93-125`) | 2026-10-03 | **stale** S6/S13 | Event count incl. demo finals; recode events count as extra; aggregate path misses today. | 7-day window is empty on dev (live fallback) | P, D | Y | Y |
| 54 | C-17 Predicted days | `dm_kpi_burndown.py:59` | 2026-10-03 | OK | Uses 6-state pending (reference definition); only as good as C-16. | - | P, D | Y | Y |
| 55 | C-18 Predicted vs achieved | `dm_kpi_burndown.py:59` (`:196-312`) | 2026-10-03 | **stale** S13 | Total includes consent-refused and DM-not-codeable (never "codeable", so remaining never reaches 0); achieved = cumulative *events* (recodes and demo counted) from a backfill that starts mid-history. Needs a target date; none set on dev. | achieved aggregate cum **1,401 vs 6,875 live events** (6 aggregate-safe sites); events 7,450 vs coded-state 7,515 vs distinct event sids 6,815 | P | Y (via unit live part) | N |

### 1h. analytics.py, MV helpers, Site-PI, dashboards

| # | KPI | file:line | Last changed | Status | Reason | cur -> fix | Level | Unit grants | Peer |
|---|---|---|---|---|---|---|---|---|---|
| 56 | `/analytics/kpi` (`get_dm_kpi_from_mv`: total, coded, pending, flagged, ODK issues, SmartVA, revoked, not analysable, workflow counts) | `analytics.py:152`; `submission_analytics_mv.py:1403`, pending `:1532` | 2026-10-27 | **stale** S5 | `pending` = 3 states; C-04 and the bucket scheme use 6. Everything else uses `_mv_scope_filter` (retired, duplicate, unit subtree, training) correctly. | pending **193 -> 270**; coded 7,515 same | P, D, U | Y | Y |
| 57 | `/analytics/submissions/by-*` | `analytics.py:165-235` | 2026-10-24 | OK | `_mv_scope_filter`. | - | P, D | Y | Y |
| 58 | `/analytics/demographics` | `analytics.py:239` | 2026-10-24 | OK | - | - | P | Y | N |
| 59 | `/analytics/workflow` | `analytics.py:295` | 2026-10-24 | OK | - | - | P | Y | Y |
| 60 | `/analytics/cod` | `analytics.py:315` | 2026-10-24 | **stale** S14 | Groups by `final_icd` (ICD-10 regex only); ICD-11 finals (`final_icd11`, primary stem) are dropped; no WHO 2026 bucket (snapshot MV has `authoritative_who_bucket`). Authority is honoured by the detail MV. | finals with ICD-10 7,881 of 7,886; **5 ICD-11 finals omitted**; bucket available for 7,884 | P, D | Y | Y |
| 61 | `get_dm_project_site_stats_from_mv` / `get_dm_org_unit_stats_from_mv` | `submission_analytics_mv.py:1630`, `:1732` | 2026-10-27 | OK | Counts only; the org-unit one is the per-unit rollup to reuse (S5b). | - | D, U | Y | **Y** |
| 62 | Site-PI workflow KPIs (project / site / unit) | `sitepi_reporting_service.py:59,209,245,270` | 2026-10-05 | OK-note | Pair-keyed, unit subtree, authority-aware, retired + duplicate filtered. Event counts have no demo exclusion (S6, minor). | - | D, U | Y | N |
| 63 | Area dashboard / coder dashboard / reviewer dashboard | `area_dashboard_service.py`, `coder_dashboard_service.py:119`, `reviewer_dashboard_service.py` | 2026-10-23/24 | OK | Training and demo-training projects excluded, bucket scheme, duplicates, retired. Coder output counts distinct authored finals. Keep as the reference. | - | D, U / own | Y | **Y (area)** |

## 2. Stale issues and corrected sketches

Common building blocks to reuse, no new scoping code:
- `DmScope.sql()`, `outside_aggregates_sql()`, `params`, `grant_in_scope_sql()`
  (`dm_kpi_scope.py`); `dm_grant_scope`, `_mv_scope_filter` (MV readers).
- `not_confirmed_duplicate_sql("s.va_sid")`, `in_odk_sql("s")` + `IN_ODK_BIND`.
- `WORKFLOW_CODING_BUCKETS` / `coding_bucket()` / `area_breakdown_columns()` and
  `get_dm_org_unit_stats_from_mv()` for pending and per-unit slices.
- `recode_window_interval()` / `recode_windows_by_project()` (`recode_window.py`).
- `training_scope` + `VaProjectMaster.demo_training_enabled` (as
  `coder_dashboard_service.get_coder_output_summary`).

New shared constants (one module, e.g. `app/services/workflow/kpi_sql.py`,
beside `revision_request_sql.py`; derived, not retyped):
`PENDING_STATES_SQL` = awaiting_coding + in_coding states from
`WORKFLOW_CODING_BUCKETS`; `READY_POOL_STATE` = `ready_for_coding`;
`not_demo_output_sql(e, f)`.

### S1. C-01 grid: Total and Pending (`dm_kpi_grid.py`)

Why: `_grid_from_aggregates_with_live_fill` copies `new` into `total`
(`:235`); `_grid_from_live` does the same (`:319`). Pending uses 3 states
(`:172`) and is 0 for every day but today.

Fix (cumulative total for any day, one query; the base count is taken once
and the per-day counts are summed over the window):

```sql
WITH scoped AS (
  SELECT DATE(s.va_created_at) AS d
  FROM va_submissions s JOIN va_forms f ON f.form_id = s.va_form_id
  WHERE {scope.sql()} AND {in_odk} AND {not_dup}
    AND DATE(s.va_created_at) <= CURRENT_DATE),
base AS (SELECT COUNT(*) AS n FROM scoped WHERE d < :from_date),
per_day AS (SELECT d, COUNT(*) AS n FROM scoped WHERE d >= :from_date GROUP BY d)
SELECT g::date AS day,
       (SELECT n FROM base) + COALESCE(SUM(p.n) OVER (ORDER BY g), 0) AS total
FROM generate_series(:from_date::date, CURRENT_DATE, '1 day') g
LEFT JOIN per_day p ON p.d = g::date;
```
Verified on dev (Scope A, 8-day window): 7,804 -> 7,808 -> 7,811, today 7,811, monotonic.
Pending: show today's live `PENDING_STATES_SQL` count; for past days without a
stored row return `null` (not 0) and let the client render a dash.

Plan check: the scoped CTE is the same shape as `_live_daily_counts`
(`ix_va_submissions_va_form_id` bitmap + `ix_va_submissions_va_created_at`);
dev EXPLAIN of the 6-state scoped scan: GroupAggregate over a bitmap scan on
`ix_va_submissions_va_form_id` with `ix_va_submission_workflow_va_sid` lookups;
no seq scan on submissions/events. Dev tables are small (8.6k submissions,
55k events), so confirm at production size with `EXPLAIN (ANALYZE, BUFFERS)`
before merging.

Tests: `tests/routes/test_dm_kpi_grid.py` (extend): grid with no aggregate
row for the last 8 days returns cumulative `total` equal to the scoped count,
monotonic non-decreasing; a past live-filled day has `pending is None`;
unit-grant DM total equals the subtree count once (direct pair + subtree row
counted once).

### S2. Stored aggregates (`kpi_tasks.py`, `va_daily_kpi_aggregates`)

1. **Not scheduled.** No periodic row, no `ensure_*_scheduled`, no call after
   sync. Add `ensure_daily_kpi_snapshot_scheduled()` in `kpi_tasks.py` modelled
   on `ensure_coding_timeout_cleanup_scheduled` (`sync_tasks.py:2702`) and call it
   next to the other ensure calls; run for yesterday and today.
   Migration: none (the Celery beat DB scheduler row is created by the ensure
   function). Owner decision Q1 on the timezone.
2. **Site-keyed rows.** Policy says `(snapshot_date, project_id, site_id)`;
   the model PK is `(snapshot_date, site_id)` and `project_id` is "latest
   owner". `_aggregate_safe_sites` already guards the leak, at the cost of
   live fallback for every shared site. Real fix = migration adding
   `project_id` to the PK (additive: new unique index, backfill by recompute,
   then swap), and `org_unit_id` rows for organization projects (gap G3).
   Defer; the guard is safe.
3. **Intake source.** `new_from_odk` / `updated_from_odk` count web intake.
   Add `new_web` or split by `va_forms.form_source`; until then rename the
   label to "New" in the grid and keep the column.
4. **End-of-day columns are not history.** `_count_pending_eod` and
   `_count_upstream_changed_eod` read *current* state. If the task runs daily
   on yesterday, the value is "state at 00:30 today", acceptable; any backfill
   writes current state on old dates (dev: 17 backfilled days). Either stop
   offering backlog history older than the first scheduled run, or replay:

```sql
-- state of each case at end of :d, from the last event <= :d 23:59:59
SELECT COUNT(*) FROM (
  SELECT DISTINCT ON (e.va_sid) e.va_sid, e.current_state
  FROM va_submission_workflow_events e
  WHERE e.event_created_at < (:d::date + 1)
  ORDER BY e.va_sid, e.event_created_at DESC, e.workflow_event_id DESC) last
WHERE last.current_state = ANY(:pending_states);
```
   (`state_set_direct` events, 19 on dev, are bulk sets; they are events too,
   so replay includes them.)
5. **Demo exclusion** for event columns (S6). **Duration** columns (S3).

Tests: `tests/test_kpi_tasks.py`: scheduled-task registration test (ensure is
idempotent, one row); aggregate pending uses the shared constant; a site with
two projects keeps `_aggregate_safe_sites` false for each.

### S3. C-08 time to code (`dm_kpi_pipeline.py:186-205`, `kpi_tasks.py:442-483`)

```sql
SELECT COUNT(*) AS cnt,
       MIN(x.secs) AS min_dur, MAX(x.secs) AS max_dur,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x.secs) AS p50_dur,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY x.secs) AS p90_dur
FROM va_submission_workflow_events e2
JOIN va_submissions s ON s.va_sid = e2.va_sid
JOIN va_forms f ON f.form_id = s.va_form_id
JOIN va_project_master pm ON pm.project_id = f.project_id
CROSS JOIN LATERAL (
    SELECT EXTRACT(EPOCH FROM e2.event_created_at - MAX(e1.event_created_at)) AS secs
    FROM va_submission_workflow_events e1
    WHERE e1.va_sid = e2.va_sid
      AND e1.transition_id IN ('coding_started', 'recode_started')
      AND e1.event_created_at <= e2.event_created_at
    HAVING MAX(e1.event_created_at) IS NOT NULL
) x
WHERE {scope.sql()} AND {in_odk} AND {not_dup}
  AND e2.transition_id IN ('coder_finalized', 'recode_finalized')
  AND e2.event_created_at >= :cutoff
  AND pm.demo_training_enabled IS NOT TRUE
  AND NOT EXISTS (SELECT 1 FROM va_submission_workflow_events d
                  WHERE d.va_sid = e2.va_sid AND d.transition_id = 'demo_started');
```

EXPLAIN (dev, 7-day cutoff): Index Scan on
`ix_va_submission_workflow_events_event_created_at` for e2, Index Scan
`ix_va_submissions_va_sid`, lateral Bitmap scan on
`ix_va_submission_workflow_events_sid_created (va_sid, event_created_at)`.
No new index needed. Dev result without the 7-day cutoff: 6,877 rows,
p50 148.6 s, max 4,121 s.

Tests: seed one case with two `coding_started` events and a recode; assert one
duration per finalization and no negative value; assert a demo-session case
and a `demo_training_enabled` project are excluded; assert a case with a
`recode_started` pairs with that start, not the first one.

### S4. C-23 blocked forms (`dm_kpi_exclusions.py:372-440`)

Restrict every breakdown row and the dedupe total to the coding pool of
uncoded work (`PENDING_STATES_SQL`), i.e. add to "missing language", "ODK
flagged" and `total_blocked`:

```sql
AND w.workflow_state = ANY(:pending_states)       -- 6 uncoded states
```
`finalized_upstream_changed` / `sent_back_for_revision` stay as their own
rows (they are coded cases waiting on a DM) and stay in the total; so
`total_blocked` = uncoded blocked + upstream. ODK flagged becomes
"pending and ODK flagged". Dev: 145 -> 81, ODK flagged 71 -> 4.
Index: `ix_va_submission_workflow_state_va_sid (workflow_state, va_sid)`.
Tests: a reviewer_eligible case with NULL language and a hasIssues flag adds
nothing; an attachment_sync_pending case with NULL language counts once in the
total and once per applicable row.

### S5. One pending definition

Adopt the bucket scheme: **Pending coding** = awaiting_coding + in_coding
(screening, attachment_sync, smartva, ready, coding_in_progress, step1_saved)
everywhere it is shown as "pending": grid live (`:172`), `get_dm_kpi_from_mv`
(`:1532`), C-22 (`:546-563`), D-WT-03 live (`:709`), and the stored
`pending_count` already does. **Ready pool** = `ready_for_coding` keeps C-07,
C-15/C-20/D-LC-03 (pool by policy; Q2) and the D-WT-03 *name*: either rename it
"Ready-pool backlog" and store `ready_count`, or switch it to the 6-state
series; recommended: 6-state, since the stored series already is.
Policy `docs/policy/kpis.md` contradicts itself (grid row and C-20 say 3
states, C-04 says 6): amend first (AGENTS.md: policy baseline before code).
Dev: 193 -> 270 (+40%); MV and live agree (193/270 both).
Tests: one parametrised test that the shared constant equals the area
dashboard's awaiting+in_coding buckets (a state added to the workflow
definition fails it).

### S5b. Org-model fit: per-unit slice and peer comparison (C-22 and family)

C-22 groups by `f.site_id`; an organization project has one automatic site,
so a district DM gets one row. For organization projects, group by the DM's
immediate child units (the area dashboard's level logic), for sites projects
by `(project_id, site_id)`:

```sql
-- sites mode
SELECT f.project_id, f.site_id, <pending6> AS pending, <pool> AS pool ...
GROUP BY f.project_id, f.site_id
-- organization mode: reuse the rollup, do not write a new ltree query
get_dm_org_unit_stats_from_mv(project_id=..., unit_ids=<children of selected unit>,
                              include_breakdown=True)   # awaiting_coding + in_coding per unit
```
The same slice (`by=unit`) should serve C-04, C-07, C-09, C-12, C-14, C-23,
D-QG-01 and C-06 ("Peer = Y" in the tables). Rules: compare only siblings at
one level (PHCs of a CHC, CHCs of a block, districts of a state), never a unit
with a different level; rates need the same denominator definition per peer;
reuse the area dashboard's small-number suppression (`suppress_causes`,
docs/policy/area-dashboard.md) so a unit with a handful of cases is not
ranked. Project-level KPIs (Tier 1) compare districts, not facilities, and
carry no PII. A unit grant sees its own subtree's children, never siblings
above it (access-control-model.md: a grant confers nothing above its unit).
EXPLAIN: the rollup is a single query on `ix_va_submission_analytics_core_mv_org_unit_path`
(per its docstring); not re-run here (MV plan on dev is trivial).
Tests: district DM sees only its blocks; PHC DM sees only its sub-centres;
peers of different levels never mixed; suppression under the threshold;
a submission routed to two nested granted units counts once.

### S6. Demo contamination of event KPIs

SADEMO (`demo_training_enabled = true`) shows 573 `coder_finalized` /
`recode_finalized` events on 23 submissions in Scope A. C-08 skips cases with
`demo_started`; C-01 coded, stored `coded_count`, C-12-by-events, C-16, C-18,
C-19 outflow, D-LC rate maps do not. The coder dashboard already excludes
`demo_training_enabled` projects. Fix = one predicate in the shared module:

```sql
AND pm.demo_training_enabled IS NOT TRUE          -- join va_project_master on f.project_id
AND NOT EXISTS (SELECT 1 FROM va_submission_workflow_events d
                WHERE d.va_sid = e.va_sid AND d.transition_id = 'demo_started')
```
Dev: events 7,450 -> 6,877 (-7.7%); distinct submissions 6,838 -> 6,815.
State-based KPIs (C-04, C-05, flowchart) are unchanged: those are the cases'
real states. Owner decision Q3: should a DM of a demo project see output
KPIs for it at all.
Tests: demo project events excluded from grid coded, burndown rate and
inflow/outflow; a non-demo project unaffected; a stored aggregate recount
(`recompute_kpi_days_for_submission`) drops demo events too.

### S7. C-19 inflow (`dm_kpi_pipeline.py:484-495`)

Inflow = events whose target state is `ready_for_coding` that start a case:

```sql
CASE WHEN e.current_state = 'ready_for_coding'
          AND e.transition_id IN ('smartva_completed','smartva_failed_recorded',
                                  'admin_override_to_recode')            THEN 'inflow'
     WHEN e.current_state = 'ready_for_coding'
          AND e.transition_id IN ('incomplete_first_pass_reset',
                                  'tester_coding_returned')              THEN 'returned'
     WHEN e.transition_id IN ('coder_finalized','recode_finalized')       THEN 'outflow' END
```
`demo_reset` is excluded (demo). Index `ix_va_submission_workflow_events_transition_created`
(or current_state). Dev cumulative inflow 6,923 -> 7,107; 90 d 41 -> 44;
returned 497 / 31.
Tests: a SmartVA-failed case counts as inflow; a first-pass reset counts as
"returned", not inflow; demo_reset ignored.

### S8. D-QG-09 disagreement (`dm_kpi_coders.py:318-345`)

Use the snapshot MV, which already resolves authority and buckets:

```sql
SELECT COUNT(*) AS total_reviewed,
       COUNT(*) FILTER (WHERE m.coder_final_who_bucket IS DISTINCT FROM m.reviewer_final_who_bucket
                          OR (m.coder_final_who_bucket IS NULL AND
                              COALESCE(m.coder_final_icd11_stem, m.coder_final_icd)
                              IS DISTINCT FROM
                              COALESCE(m.reviewer_final_icd11_stem, m.reviewer_final_icd))) AS disagreements
FROM va_submission_cod_snapshot_mv m
JOIN va_submissions s ON s.va_sid = m.va_sid
JOIN va_forms f ON f.form_id = s.va_form_id
WHERE {scope.sql()} AND {in_odk} AND {not_dup}
  AND m.coder_final_assessment_id IS NOT NULL
  AND m.reviewer_final_assessment_id IS NOT NULL;
```
Dev: 2/3 -> 1/3 (ICD-10 level 0/3). The MV holds active finals; the
authoritative one is separate (`authoritative_source`), so report both
"coder vs reviewer" and, optionally, "authority overrode coder" count.
Caveat: MV freshness (hourly refresh, `celery_periodictask` "Submission
analytics MV refresh"). Owner decision Q4: bucket vs ICD-code level.
Tests: same ICD-10 code with different free text = agree; different codes in
the same WHO bucket = agree; ICD-11 `A/B` vs `A` primary stem agree.

### S9. Language match and coder counts (`dm_kpi_language.py`, `dm_kpi_coders.py`)

- Match as allocation does: `lower(trim(lang))`; coders with an empty
  `vacode_language` cover every language. Build the coder set with
  `lower(trim(unnest(vacode_language)))` and compare to `lower(trim(s.va_narration_language))`
  (index `ix_va_submissions_form_lower_language_sid` already exists on
  `lower(va_narration_language)`). Dev: "English" 0 -> 98 coders.
- Coders for a unit scope: coders whose grant *covers* the DM's subtree
  (project grant, or a unit grant that is an ancestor or descendant), not every
  coder in the project:

```sql
SELECT COUNT(DISTINCT g.user_id)
FROM va_user_access_grants g
LEFT JOIN mas_org_unit gu ON gu.org_unit_id = g.org_unit_id AND gu.is_active
WHERE g.role = 'coder' AND g.grant_status = 'active'
  AND ( g.scope_type = 'project' AND g.project_id = ANY(:grant_project_ids)
     OR g.scope_type = 'project_site' AND <pair in scope>
     OR g.scope_type = 'org_unit' AND EXISTS (
          SELECT 1 FROM mas_org_unit a
          WHERE a.org_unit_id = ANY(CAST(:unit_ids AS uuid[]))
            AND (gu.path <@ a.path OR gu.path @> a.path)));
```
  Dev TST001, DM granted PHC01: 5 -> 4 (1 under the roster's stricter rule).
  The roster (D-LC-06) names coders and keeps `grant_in_scope_sql`; counts may
  use the covering rule (Q5). Also subtract coders blocked by self-coding
  rules where a project enables `self_coding_enabled` (gap G5).
Tests: mixed-case language; coder with no languages; DM at PHC01 does not count
the PHC02-only coder; project-site DM unchanged.

### S10. Recode window (`dm_kpi_pipeline.py:263`, `dm_kpi_workflow.py:190,193,439,136,155`)

Join `va_project_master` and compare with the per-project interval:

```sql
JOIN va_project_master pm ON pm.project_id = f.project_id
... AND e.event_created_at < NOW() - (pm.recode_window_minutes * INTERVAL '1 minute')
-- flowchart split
COUNT(*) FILTER (WHERE w.workflow_updated_at >= NOW() - (pm.recode_window_minutes * INTERVAL '1 minute')) AS within_window
```
(`recode_window_interval()` renders exactly that on the ORM side.) Rename the
response keys `within_24h`/`beyond_24h` to `within_window`/`beyond_window`
and keep the old keys one release for the Expo client. Stagnation: coder_finalized
"normal" threshold becomes the project's window, shown as `window_minutes`.
Dev: identical (all 1440). Tests: a 60-minute project with a case finalized 2 h
ago is "beyond window" and in the reviewed denominator; a 1440 project is not.

### S11. C-13 / C-14 intake source (`dm_kpi_sync.py:196,258-275`)

Add `AND f.form_source = 'odk'` to both (web intake has no ODK submission time
and no Central attachments). Optionally add a web-intake KPI instead: median
time from interview end to submit (not stored today, gap G2).
Dev: C-14 missing 9/7,734 -> 1/7,726; C-13 rows 7,808 -> 7,803.
Tests: a web case with zero attachments is not in the C-14 denominator.

### S12. NQA / SA project join (`dm_kpi_exclusions.py:484-491`)

Replace the COALESCE-subquery with `JOIN va_project_master pm ON pm.project_id = f.project_id`.
No dev change today; MH01 is shared by KEM001 and KEMDEM, which differ on
`social_autopsy_enabled`, so a SA denominator can flip with row order of
`va_project_sites`. Tests: two projects at one site with different flags each
count only their own coded cases.

### S13. C-16 / C-18 (`dm_kpi_burndown.py`)

- Coded = **distinct submissions** that reached coded, not events:
  `COUNT(DISTINCT e.va_sid)` over first `coder_finalized`/`recode_finalized`
  (or count `WORKFLOW_CODING_BUCKETS == coded` states for the cumulative line).
  Dev: events 7,450 / sids 6,815 / coded states 7,515: the three disagree
  because 7,887 `reviewer_eligible_after_recode_window` events exist but
  imported cases have no finalization event, so state-based is the cumulative
  truth and the events are the *rate* source.
- `total_forms` = coding pool (exclude consent_refused, not_codeable_by_data_manager).
- Achieved line from aggregates only when the stored series covers
  the project start; otherwise use live events (`_achieved_with_units` already
  does for the non-aggregate part).
Tests: recode does not raise cumulative; remaining reaches 0 when all pool cases
are coded; refused cases not in total.

### S14. `/analytics/cod` (`analytics.py:315-358`)

Read the snapshot MV: `COALESCE(authoritative_who_bucket, ...)` for a bucket
view, and `COALESCE(coder_final_icd11_stem, coder_final_icd)` for code view,
or add `final_icd11` from `va_submission_cod_detail_mv` (the detail MV
already carries it, `c5e8a2f4b7d1`). Dev: 7,881 -> 7,886 finals (5 ICD-11);
bucket 7,884. Tests: an ICD-11 final appears under its primary stem; a
post-coordinated `A/B` is counted under `A`.

## 3. Policy and doc drift to fix first (`docs/policy/kpis.md`, last_updated 2026-10-09)

- Pending definition (S5); `pending_count` and C-01 columns.
- `va_daily_kpi_aggregates` key: policy says `(date, project, site)`, model is
  `(date, site)`.
- `new_from_odk` source: policy says `va_sync_runs.records_added`; code counts
  created submissions (ODK and web).
- C-09 and D-WF-03: "24h" -> the project's recode window.
- D-QG-03: reviewer-rejection item not implemented.
- D-SH-01: denominator.
- `daily_kpi_aggregation_timezone` / `daily_kpi_aggregation_time` settings:
  not implemented; day boundaries are the database clock (UTC on dev; India
  users see a 05:30 shift). Q1.
- Add: demo exclusion rule (S6), intake-source rule (S11), peer-comparison
  rules (S5b), WHO bucket / authority for COD KPIs (S8, S14).
- `docs/current-state/data-manager-dashboard.md` and `submission-analytics.md`
  follow the same edits.

## 4. Gaps: data that is not stored

- G1. Historical recode window per project (a change is not versioned); use
  the current value.
- G2. Web intake timings (interview start/end vs submit) are not a column;
  no web counterpart of C-13.
- G3. Aggregates by organization unit: no `org_unit_id` on
  `va_daily_kpi_aggregates`, so unit grids are always live; a submission's
  `org_unit_id` can be re-routed (`org_unit_pinned_by`), so past per-unit counts
  follow today's routing. Needs the (date, project, org_unit) snapshot if unit
  history is wanted.
- G4. Events carry no lane tag (demo / tester / real): the exclusion is
  per submission (the existing `ponytail` note at `dm_kpi_workflow.py:341`);
  a case coded for real and later demoed loses events.
- G5. Self-coding: who interviewed an ODK case is free-text
  `va_data_collector` (not a user id), so capacity KPIs cannot subtract
  blocked self-coders for ODK; web cases have the interviewer in the register.
- G6. No per-enumerator / per-interviewer KPI (collector productivity,
  outcome mix) is defined; `va_data_collector` holds names (PII).
- G7. Dev has no real organization-tree volume to validate the unit-subtree and
  peer slices numerically.
- G8. Historical pending / upstream (S2.4) is reconstructible from events but
  not stored.

## 5. Owner questions

- Q1. Day boundary: UTC database clock, project timezone, or app setting?
- Q2. Language-gap pendency: ready pool (3 states, policy) or whole pipeline?
- Q3. Do DMs of a `demo_training_enabled` project see output KPIs for it?
- Q4. D-QG-09 level: WHO 2026 bucket (recommended) or ICD code?
- Q5. Utilization denominator for a unit DM: coders covering the subtree (4 on
  the TST001 example) or only grants inside it (1)?
- Q6. Peer-comparison suppression threshold: reuse the area dashboard's.

## 6. Suggested order (when approved)

1. Policy edits (section 3).
2. Shared constants + demo and window helpers; S5 (pending), S10, S11, S12.
3. S3, S4, S7, S8, S9, S13, S14 with tests.
4. S1 + S2 (schedule the task; recount via `flask kpi backfill` after the
   duration fix).
5. S5b per-unit slice and peer comparison (largest; needs UI decisions).
Run targeted tests per item; one full suite at the end.

---

## Opus advisor review and recommended path (2026-10-27)

**Spot-check:** C-01, C-08, the unscheduled snapshot, the language case bug
and the pending split are all confirmed. Pending is split three ways, not
two:
- 3 states: grid, language, exclusions, pipeline, MV and JS;
- 6 states: `kpi_tasks`, pipeline:85 and burndown;
- 1 state: the live backlog trend.

**Audit corrections:**
- `/refresh` and duplicate confirm or reopen do write aggregates. A
  refreshed today row then serves stale data.
- Grid bugs the audit missed:
  - the day's new count is added onto the cumulative Total;
  - days with no activity vanish, and pending lands on the last active
    date;
  - `date.today()` is compared with the database's `DATE()`.
- C-21 is an owner decision (`access-control-model.md:642-645`,
  `digitva-4b3e`), not a defect.
- Two of the test files the audit names do not exist.
- No new `kpi_sql.py` is needed: `workflow/definition.py` already holds the
  shared predicates.

**Snapshot: retire the stored aggregates as a read source and compute live.
Do not schedule or backfill.**
- End-of-day state is rebuilt from workflow events (`previous_state`,
  `current_state`) over the window:
  `count_P(end of d) = count_P(now) - sum of events after d of ([cur in P] - [prev in P])`.
- That gives viewer-timezone days, unit subtrees and per-project recode
  windows.
- `flask kpi backfill` would stamp today's state onto past dates.
- Keep the table and model. No migration.
- Gate: `EXPLAIN (ANALYZE, BUFFERS)` on the burndown from project start at
  production size.

**Q1–Q6 recommendations:**

| Question | Recommendation |
|---|---|
| Q1 | Viewer timezone (default Asia/Kolkata) at query time. Coding gates stay UTC. Drop the aggregation timezone and time settings. Do not use `va_local_date` on `event_created_at`. |
| Q2 | The gap alert uses the ready pool; C-20 uses the 6-state pending set. |
| Q3 | Demo events are dropped from output and rate KPIs with one shared predicate. Demo projects stay in scope. |
| Q4 | Coder–reviewer disagreement at the WHO 2026 bucket level, from the COD snapshot MV. |
| Q5 | A unit DM's utilization denominator counts coders who can code a case in the DM's subtree. Amend `access-control-model.md:642-645`. |
| Q6 | Peer suppression with `PERCENT_MIN_WHOLE` = 20. Peers are siblings inside the viewer's grant. Counts only. |

**Canonical definitions:**
- **Pending:** the 6 states (`PENDING_STATES`).
- **Ready pool:** `ready_for_coding` (`READY_POOL_STATES`).
- **Blocked:** pending plus upstream, as one `FILTER` query.
- **Coded:** as a state, the coded bucket; as output, non-demo finalize
  events.
- **Time to code:** each finalize paired with the latest start (`LATERAL`).
- **Inflow and outflow:** crossing the pending boundary
  (`bucket_flow_by_day`).
- **Coder availability:** `coders_covering_scope_sql()`, with
  `lower(trim())` language matching and empty meaning any.

**Steps.** None needs a migration.
0. Policy: amend `kpis.md` and `access-control-model.md`, then mirror the
   changes in current-state, the CLI reference and help.
1. Shared constants in `definition.py`.
2. Live-only grid and flow helper; delete the aggregate branches,
   `/refresh` step 1, the recompute hook and the `flask kpi` commands.
3. Time to code.
4. C-23 blocked.
5. Recode window: `within_window`, keeping `within_24h` for one release.
6. Coder availability and language.
7. Small fixes (S11, S12, S8/S14, D-LC-01).
8. Peer slice, last.

Step 1 comes first. Steps 3–7 can run in parallel after it. Step 2 comes
after 1, and step 8 after 2.

**Do not:**
- schedule or backfill;
- add the timezone settings;
- migrate the aggregate key;
- add a new SQL module;
- drop the table;
- drop `within_24h` without a release of overlap.

**Defer:** G2–G6, and a stored series unless the `EXPLAIN` misses budget.
