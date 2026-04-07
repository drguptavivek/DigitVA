---
title: Data Manager KPI Framework
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-04-07
---

# Data Manager KPI Framework

> **Implementation plan:** [`.tasks/kpis-policy.md`](../../.tasks/kpis-policy.md)

## Context

Project-site data managers need a systematic, measurable KPI framework to monitor DigitVA system performance. This plan creates a formal `docs/policy/kpis.md` with precise definitions for every KPI — exact numerator/denominator with inclusion/exclusion rules — so they can be systematically measured and compared.

KPIs are split into **Core** (daily dashboard, ~15 KPIs) and **Detailed** (drill-down analytics, ~25 KPIs).

---

## DM Scoping Rules

A data manager's visibility is determined by their grants in `va_user_access_grants`:

- **Project-level grant** (`scope_type = 'project'`): DM sees all sites within that project.
- **Project-site grant** (`scope_type = 'project_site'`): DM sees only that specific project-site pair.
- A single DM may hold multiple grants across different projects and project-site pairs.
- **Every KPI denominator is filtered through `dm_scope_filter(user)`** — a DM only sees data for the projects/sites they have grants for.
- When the dashboard shows project-level or site-level breakdowns, it only shows projects/sites within the DM's scope.

---

## KPI Storage: Hybrid Model

### `va_daily_kpi_aggregates` table

Pre-computed daily grid columns. One row per `(snapshot_date, project_id, site_id)`.

| Column | Type | Source |
|--------|------|--------|
| `snapshot_date` | DATE | The calendar date this row represents |
| `project_id` | VARCHAR(6) | FK to `va_project_master` |
| `site_id` | VARCHAR(4) | FK to `va_site_master` |
| `total_submissions` | INT | COUNT of ALL-SYNCED as of end of day |
| `new_from_odk` | INT | SUM of `va_sync_runs.records_added` for runs that day |
| `updated_from_odk` | INT | SUM of `va_sync_runs.records_updated` for runs that day |
| `coded_count` | INT | COUNT of coder_finalized events that day |
| `pending_count` | INT | COUNT in ready_for_coding + coding_in_progress + coder_step1_saved (end-of-day) |
| `consent_refused_count` | INT | COUNT of consent_refused events that day |
| `not_codeable_count` | INT | COUNT of not_codeable events (coder + DM) that day |
| `coding_duration_min` | INTERVAL | Min coding duration for finalizations that day |
| `coding_duration_max` | INTERVAL | Max coding duration for finalizations that day |
| `coding_duration_p50` | INTERVAL | Median (P50) coding duration for finalizations that day |
| `coding_duration_p90` | INTERVAL | P90 coding duration for finalizations that day |
| `reviewer_finalized_count` | INT | COUNT of reviewer_finalized events that day |
| `upstream_changed_count` | INT | COUNT of upstream_change_detected events that day |
| `reopened_count` | INT | COUNT of reopen events that day |
| `created_at` | TIMESTAMPTZ | When this row was inserted |

**Populated by:** Celery task, runs at configured time daily (see App-Level Settings below) + after each sync run.
**Purpose:** Fast dashboard grid + time-series charts without expensive event-table queries.

### App-Level Settings

Admin-configurable settings (stored in `mas_app_settings` or equivalent):

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `daily_kpi_aggregation_timezone` | STRING | `UTC` | Timezone for daily snapshot boundaries (e.g., `Asia/Kolkata`, `Australia/Sydney`) |
| `daily_kpi_aggregation_time` | TIME | `00:30` | Time (in configured timezone) to run the daily aggregation Celery task |
| `project_target_completion_date` | DATE (per project) | NULL | Target date for completing all coding. Enables predicted-vs-achieved charts. |

These are app-level (not per-project) for timezone and aggregation schedule. The target completion date is per-project.

### Event-sourced detail

Detailed KPIs (reason breakdowns, language gaps, per-coder stats) computed on-demand from:
- `va_submission_workflow_events` — for transition-level detail
- `va_submission_analytics_core_mv` / `demographics_mv` — for MV-backed aggregations
- `va_coder_review`, `va_data_manager_review`, `va_reviewer_review` — for reason breakdowns

---

## Hard Gates & Denominator Scopes

```
All Synced Submissions
  │
  ├─ HARD GATE: Consent (consent=no → consent_refused)
  │   Permanent exclusion. Form never enters pipeline.
  │   Scope: CONSENT-VALID = ALL-SYNCED − consent_refused
  │
  ├─ SOFT GATE: DM Not-Codeable (→ not_codeable_by_data_manager)
  │   Reversible. If ODK data is updated/corrected, form may become codeable.
  │   Included in CONSENT-VALID but excluded from CODING-POOL.
  │
  ├─ SOFT GATE: Coder Not-Codeable (→ not_codeable_by_coder)
  │   Reversible. Form entered coding pool but coder couldn't process it.
  │   Included in CODING-POOL denominator (was eligible), excluded from CODED.
  │
  └─ CODED = reached coder_finalized or beyond
```

| Scope | Definition | Inclusions | Exclusions |
|-------|-----------|------------|------------|
| **ALL-SYNCED** | Every row in `va_submissions` within DM scope | All submissions, all states | None |
| **CONSENT-VALID** | ALL-SYNCED minus consent_refused | Everything except consent=no | `workflow_state = 'consent_refused'` only |
| **CODING-POOL** | CONSENT-VALID minus DM-not-codeable | Submissions that entered or could enter coding | `consent_refused`, `not_codeable_by_data_manager` |
| **CODED** | Submissions that reached coder_finalized or beyond | `coder_finalized`, `reviewer_eligible`, `reviewer_coding_in_progress`, `reviewer_finalized`, `finalized_upstream_changed` | Everything else |

**Key distinction:**
- **Hard gate** (`consent_refused`): permanent, excluded from all downstream scopes
- **Soft gates** (`not_codeable_by_data_manager`, `not_codeable_by_coder`): reversible. ODK data updates or admin override can return these forms to the pipeline. These should be tracked and surfaced to the DM as "actionable" rather than "lost."

---

## Time Frames

| Frame | Definition |
|-------|-----------|
| **Today** | Since midnight in the project's configured timezone |
| **Yesterday** | Previous calendar day |
| **Last 7 days** | Rolling 7 calendar days including today |
| **Cumulative** | All-time since first submission in scope |

---

## CORE KPIs — Daily Dashboard (~15 KPIs)

### C-01: Daily Operations Grid

A 7-column table, last 8 rows (today + 7 prior days), slicable by project and site.

| Column | Numerator | Denominator | Scope | Source |
|--------|-----------|-------------|-------|--------|
| **Total** | COUNT of ALL-SYNCED submissions as of end of that day | — | ALL-SYNCED | `va_submissions` |
| **New from ODK** | SUM of `va_sync_runs.records_added` for runs where `DATE(started_at) = row_date` | — | N/A | `va_sync_runs` |
| **Updated in ODK** | SUM of `va_sync_runs.records_updated` for runs where `DATE(started_at) = row_date` | — | N/A | `va_sync_runs` |
| **Coded** | COUNT of `va_submission_workflow_events` where `transition_id IN ('coder_finalized', 'recode_finalized')` and `DATE(event_created_at) = row_date` | — | CODED | `va_submission_workflow_events` |
| **Pending Coding** | COUNT where `workflow_state IN ('ready_for_coding', 'coding_in_progress', 'coder_step1_saved')` as of end of that day | — | CODING-POOL | `va_submission_workflow` |
| **Consent Refused** | COUNT of events where `transition_id` resulting in `current_state = 'consent_refused'` and `DATE(event_created_at) = row_date` | — | ALL-SYNCED | `va_submission_workflow_events` |
| **Not Codeable** | COUNT of events where `transition_id IN ('coder_not_codeable', 'data_manager_not_codeable')` and `DATE(event_created_at) = row_date` | — | ALL-SYNCED | `va_submission_workflow_events` |

### C-02: Last Sync Run Status

- **Definition:** `status` from most recent `va_sync_runs` row, plus `started_at` and `finished_at`
- **Source:** `va_sync_runs` ORDER BY `started_at DESC LIMIT 1`
- **Time Frame:** Snapshot

### C-03: Sync Error Rate

- **Numerator:** COUNT of `va_sync_runs` where `status IN ('error', 'partial')` and `started_at ≥ window_start`
- **Denominator:** COUNT of all `va_sync_runs` where `started_at ≥ window_start`
- **Rate:** N / D × 100
- **Time Frames:** 7d, cumulative

### C-04: % Uncoded (Pending Rate)

- **Numerator:** COUNT where `workflow_state IN ('ready_for_coding', 'coding_in_progress', 'coder_step1_saved', 'smartva_pending', 'screening_pending', 'attachment_sync_pending')`
- **Denominator:** COUNT of CODING-POOL
- **Rate:** N / D × 100
- **Scope:** CODING-POOL
- **Time Frames:** Snapshot, also daily in grid
- **Meaning:** What fraction of the eligible pipeline has NOT been coded yet

### C-05: % Not Codeable (Overall)

- **Numerator:** COUNT where `workflow_state IN ('not_codeable_by_coder', 'not_codeable_by_data_manager')`
- **Denominator:** COUNT of ALL-SYNCED
- **Rate:** N / D × 100
- **Scope:** ALL-SYNCED
- **Time Frames:** Today, 7d, cumulative
- **Drill-down:** By actor (coder vs DM) and by reason

### C-06: Consent Refusal Rate

- **Numerator:** COUNT where `workflow_state = 'consent_refused'`
- **Denominator:** COUNT of ALL-SYNCED
- **Rate:** N / D × 100
- **Time Frames:** Today, 7d, cumulative

### C-07: Pipeline Aging (Stagnation)

- **Definition:** COUNT of submissions where `workflow_state = 'ready_for_coding'` AND `workflow_updated_at < now() − interval '48 hours'`
- **Also report:** Same count at thresholds: >48h, >7d, >30d
- **Source:** `va_submission_workflow` JOIN `va_forms` for scope
- **Scope:** CODING-POOL
- **Time Frame:** Snapshot

### C-08: Time to Code (Min / Max / Median / P90)

- **Definition:** For each submission finalized in the window, compute `coder_finalized_event.event_created_at − coding_started_event.event_created_at`
- **Aggregates:** MIN, MAX, PERCENTILE(0.5), PERCENTILE(0.90)
- **Source:** Paired `va_submission_workflow_events` rows (same `va_sid`, matching `coding_started` → `coder_finalized`/`recode_finalized`)
- **Scope:** CODING-POOL
- **Inclusions:** First-pass coding AND recode episodes
- **Exclusions:** Demo sessions (`demo_started` transition)
- **Time Frames:** Today, yesterday, 7d

### C-09: % Forms Reviewed

- **Numerator:** COUNT of submissions that have at least one `va_reviewer_final_assessments` row with active status
- **Denominator:** COUNT of submissions that ever reached `coder_finalized` (i.e., CODED scope, excluding those still in coder-finalized if reviewer window hasn't passed)
- **Refined denominator:** COUNT where `workflow_state IN ('reviewer_eligible', 'reviewer_coding_in_progress', 'reviewer_finalized')` OR has a reviewer_finalized event in history
- **Rate:** N / D × 100
- **Scope:** CODED
- **Time Frames:** 7d, cumulative
- **Note:** 24h recode window means reviewer-eligible forms can't be reviewed immediately. Denominator excludes `coder_finalized` forms less than 24h old.

### C-10: Upstream Change Queue

- **Definition:** COUNT where `workflow_state = 'finalized_upstream_changed'`
- **Source:** `va_submission_workflow` WHERE `workflow_state = 'finalized_upstream_changed'`
- **Scope:** CODED
- **Time Frame:** Snapshot

### C-11: % Forms with Upstream Changes

- **Numerator:** COUNT of submissions that have at least one `va_submission_workflow_events` row with `transition_id = 'upstream_change_detected'`
- **Denominator:** COUNT of CODED submissions
- **Rate:** N / D × 100
- **Scope:** CODED
- **Time Frames:** 7d, cumulative
- **Meaning:** What fraction of coded forms had ODK data change after finalization

### C-12: Coder Throughput

- **Numerator:** COUNT of workflow events with `transition_id IN ('coder_finalized', 'recode_finalized')` in window
- **Denominator:** — (raw count)
- **Also report:** Per-coder breakdown
- **Scope:** CODING-POOL
- **Time Frames:** Today, yesterday, 7d, cumulative

### C-13: Sync Latency (ODK → App)

- **Definition:** For submissions synced in window: time between ODK submission timestamp and local DB insert
- **Formula:** `va_created_at − va_submission_date` per submission
- **Aggregates:** P50, P90, P99
- **Time Frames:** Today, 7d

### C-14: Attachment Health

- **Numerator:** COUNT of submissions past SmartVA gate where attachment count = 0
- **Denominator:** COUNT of submissions past SmartVA gate
- **Rate:** N / D × 100
- **Source:** `va_submission_attachments` JOIN `va_submissions`
- **Time Frame:** Snapshot

### C-15: Language Gap Alert

- **Definition:** COUNT of submissions in `ready_for_coding` where `va_narration_language` has zero active coders with that language in their `vacode_language`
- **Source:** `va_submissions` JOIN `va_users.vacode_language` via grants
- **Scope:** CODING-POOL
- **Time Frame:** Snapshot
- **Drill-down:** Which languages, how many submissions affected

### C-16: Mean Daily Coding Rate

- **Definition:** Average number of submissions coded per day over the trailing window
- **Formula:** SUM of `coded_count` from `va_daily_kpi_aggregates` over window / COUNT of days in window
- **Also report:**
  - Per coder: `SUM of coder_finalized events / days` grouped by `va_finassess_by`
  - Per language: `SUM of coder_finalized events / days` grouped by `va_submissions.va_narration_language`
- **Scope:** CODING-POOL
- **Time Frames:** 7d
- **Actionable:** Tells the DM "your team is averaging N forms/day" — compare against inflow rate to know if you're keeping up

### C-17: Predicted Days to Clear Backlog

- **Definition:** Estimated days to code all currently uncoded forms in the pipeline
- **Formula:** `pending_count (C-04 numerator) / mean_daily_coding_rate (C-16)`
- **Scope:** CODING-POOL
- **Time Frame:** Snapshot (recalculated daily)
- **Also report:** Per-language prediction: pending_in_language_X / daily_rate_language_X
- **Actionable:** If predicted days > 30, the DM knows they need more coders or the current coders need to accelerate
- **Edge case:** If mean_daily_coding_rate = 0 (no coding in 7d), report "∞" or "N/A"

### C-18: Predicted vs Achieved (Burndown)

- **Definition:** Chart comparing projected completion trajectory vs actual cumulative coding progress
- **Projected line:** At project start (or target date set), draw a straight line from (start, total_forms) to (target_date, 0). Daily point: `total − (days_elapsed × daily_target_rate)`
- **Achieved line:** Cumulative count of CODED submissions over time (from `va_daily_kpi_aggregates` cumulative `coded_count`)
- **Requires:** `project_target_completion_date` set by admin
- **Display:** Line chart, two lines, X-axis = time, Y-axis = remaining forms
- **Actionable:** If achieved line is above projected line, the project is behind schedule. The gap tells the DM exactly how far behind.
- **Time Frame:** Daily series from project start to target date

### C-19: Daily Inflow vs Outflow

- **Inflow (new forms entering pipeline):** COUNT of events where `transition_id IN ('sync_new_payload_routed', 'smartva_completed')` that day — forms that became available for coding
- **Outflow (forms coded):** C-01 Coded column
- **Net delta:** Inflow − Outflow
- **Display:** Side-by-side bar chart (inflow vs outflow per day, last 7d)
- **Actionable:** If inflow consistently exceeds outflow, backlog will grow. Positive net delta = falling behind. Negative = catching up.

### C-20: Language with Maximum Pendency

- **Definition:** For each language, COUNT where `workflow_state IN ('ready_for_coding', 'coding_in_progress', 'coder_step1_saved')`, ordered DESC
- **Display:** Table: Language | Pending | Coders Available | Gap (yes/no) | Predicted Days to Clear
- **Top row = the bottleneck language**
- **Scope:** CODING-POOL
- **Time Frame:** Snapshot
- **Actionable:** Immediately tells DM which language needs urgent coder recruitment or reallocation

### C-21: Coder Utilization Rate

- **Numerator:** COUNT of coders with at least one active allocation (`va_allocations` where `va_allocation_status = 'active'`)
- **Denominator:** COUNT of all active coders in DM's scope (from `va_user_access_grants` where role='coder', grant_status='active')
- **Rate:** N / D × 100
- **Time Frame:** Snapshot
- **Actionable:** If utilization is low (<70%), coders are idle — either not enough forms in their language or forms aren't being allocated. If high (>95%), coders are saturated — need more coders.

### C-22: Site-Level Bottleneck

- **Definition:** Per site: `(pending_count / total_count) × 100` — the % of a site's submissions that are still uncoded
- **Display:** Table ranked by % uncoded DESC
- **Scope:** CODING-POOL, grouped by site
- **Time Frame:** Snapshot
- **Actionable:** The site at the top of this list is the bottleneck. DM can investigate: is that site getting more submissions? Does it have fewer coders? Are forms harder to code?

### C-23: Blocked Forms Alert (Composite)

- **Definition:** COUNT and breakdown of all submissions in CODING-POOL that cannot be routed to a coder right now, grouped by blockage reason
- **Breakdown:**

| Blockage Reason | Condition | DM Action Required |
|----------------|-----------|-------------------|
| Awaiting DM screening | `workflow_state = 'screening_pending'` | Pass or reject screening |
| Attachments not synced | `workflow_state = 'attachment_sync_pending'` | Trigger attachment sync |
| Missing attachments | Past SmartVA gate but `va_submission_attachments` count = 0 | Re-trigger attachment sync; check ODK Central |
| SmartVA not run | `workflow_state = 'smartva_pending'` | Check SmartVA queue |
| Upstream change pending | `workflow_state = 'finalized_upstream_changed'` | Accept or reject upstream change |
| Missing language | `va_narration_language IS NULL/empty` | Fix language mapping |
| Unmapped language | `va_narration_language NOT IN (SELECT alias FROM map_language_aliases)` | Add alias mapping |
| Language gap | Language has zero coders | Recruit/reassign coders |
| ODK flagged | `va_odk_reviewstate = 'hasIssues'` | Coordinate with field team |

- **Overlap handling:** A single submission may have multiple conditions (e.g., not-codeable AND ODK-has-issues). The breakdown counts each condition independently (a form can appear in multiple rows). A separate "total blocked" count deduplicates by counting each form once, assigned to its **primary blockage** (highest-priority condition in the order listed above).
- **Display:** Table showing blockage type + count + action. Total blocked count shown separately.
- **Scope:** CODING-POOL (excludes `consent_refused` — that's a hard gate)
- **Note on soft gates:** `not_codeable_by_data_manager` and `not_codeable_by_coder` forms are excluded from CODING-POOL but tracked separately in C-05/D-QG-01/D-QG-02. They are NOT double-counted here. However, if ODK data updates and makes a not-codeable form potentially codeable, it would re-enter the screening pipeline.
- **Time Frame:** Snapshot
- **Actionable:** This is the DM's "to-do list" — each blockage type has a clear action. DM works through the list to unblock forms and increase throughput.

### C-24: Forms per Coder by Language

- **Definition:** For each coder × language combination, the count of forms coded (cumulative and in last 7d)
- **Display:** Heatmap table

```
              Hindi    Malayalam    Tamil    Kannada    Total
Coder A         45        12         -        -         57
Coder B         30         -        22        -         52
Coder C          -        55        18        -         73
Coder D         18        10         -       15         43
────────────────────────────────────────────────────────
Total           93        77        40       15
Available      120        85        50       40
Backlog         27         8        10       25
```

- **Numerator:** COUNT of `va_final_assessments` (active) GROUP BY (`va_finassess_by`, `va_submissions.va_narration_language`)
- **Denominator scope:** CODED
- **Also show:** Backlog per language = pending in that language − forms currently being coded in that language
- **Time Frames:** 7d, cumulative
- **Actionable:** Shows which coders are productive in which languages. DM can reallocate coders to languages with higher backlog. Also shows if a coder claims to know a language but hasn't coded any forms in it.

---

## DETAILED KPIs — Drill-Down Analytics (~25 KPIs)

### Sync Health Details

**D-SH-01: Attachment Download Completeness**
- Numerator: `va_sync_runs.attachment_downloaded` from latest run
- Denominator: `attachment_downloaded + attachment_skipped + attachment_errors` from same run
- Rate: N/D × 100
- Time Frame: Snapshot

**D-SH-02: ODK Coverage Delta**
- Definition: Per form, ODK-side submission count (from preview) minus local COUNT
- Source: Sync preview logic (live ODK call)
- Time Frame: On-demand

**D-SH-03: Locally Missing in ODK**
- Numerator: COUNT where `va_sync_issue_code = 'missing_in_odk'`
- Denominator: ALL-SYNCED
- Time Frame: Cumulative

**D-SH-04: SmartVA Failure Rate**
- Numerator: COUNT of `va_smartva_runs` where `va_smartva_outcome = 'failed'` in window
- Denominator: COUNT of all `va_smartva_runs` in window
- Rate: N/D × 100
- Time Frames: 7d, cumulative

### Workflow Throughput Details

**D-WT-01: Reviewer Throughput**
- Numerator: COUNT of events with `transition_id = 'reviewer_finalized'` in window
- Time Frames: Today, 7d, cumulative

**D-WT-02: Upstream Change Resolution Time**
- Numerator: For each resolved upstream change in 7d, `resolved_at − created_at`
- Aggregate: PERCENTILE(0.5)
- Source: `va_submission_upstream_changes`
- Time Frame: 7d

**D-WT-03: Coding Backlog Trend**
- Definition: Daily time-series of COUNT where `workflow_state = 'ready_for_coding'`
- Source: `va_daily_kpi_aggregates.pending_count`
- Display: Line chart, default 90-day window

**D-WT-04: Reopen Rate**
- Numerator: COUNT of events with `transition_id IN ('upstream_change_accepted', 'admin_override_to_recode')` in window
- Denominator: COUNT of `coder_finalized` events in window
- Rate: N/D × 100
- Scope: CODED
- Meaning: What fraction of finalized forms were re-opened for recoding
- Time Frames: 7d, cumulative

### Workflow State Distribution

**D-WF-01: CONSORT Pipeline Flowchart**
- Definition: Current count of submissions in each of the 14 workflow states, rendered as a CONSORT-style flowchart with:
  - Main trunk flowing top-to-bottom through pipeline stages
  - Branch points showing terminal states (consent_refused, not_codeable_by_*, finalized_upstream_changed)
  - Flow-through numbers at each stage (total minus cumulative branches)
  - Sub-phases within states (e.g., coder_finalized split by within/beyond 24h recode window)
  - Optional states visually distinguished from mandatory trunk states
- Source: `va_submission_workflow` GROUP BY `workflow_state`, scoped by DM sites
- Response includes:
  - `total_synced`: total submissions in DM scope
  - `nodes[]`: each node with `id`, `label`, `count` (in state), `flow_through` (reached this stage), `type` (trunk/optional/terminal/branch), `phase`, `branch_from`
  - `sub_phases` for `coder_finalized`: within_24h and beyond_24h counts
  - `conversion`: consent_valid_rate, coding_completion_rate, review_rate
- Rendering: CSS-based flowchart (no chart library). Vertical trunk with horizontal branches. Color-coded by phase.
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/flowchart`
- Time Frame: Snapshot

**D-WF-02: State Velocity**
- Definition: Average time submissions spend in each workflow state before transitioning out
- Source: CTE on `va_submission_workflow_events` computing per-transition durations, aggregated per `previous_state`
- Aggregates: AVG, P50, P90 in hours
- Response: `states[]` with `state`, `label`, `transition_count`, `avg_hours`, `p50_hours`, `p90_hours`
- Rendering: Table with sortable columns, slow states highlighted
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/state-velocity?days=30`
- Time Frame: 30d (configurable up to 90d)

**D-WF-03: State Stagnation Alerts**
- Definition: Submissions stuck in non-terminal states beyond configurable thresholds
- Expands C-07 (which only covers `ready_for_coding`) to ALL non-terminal states
- Source: `va_submission_workflow` with age buckets per state
- Stagnation thresholds per state:

| State | Normal | Alert | Critical |
|-------|--------|-------|----------|
| attachment_sync_pending | <2h | >2h | >24h |
| screening_pending | <24h | >48h | >7d |
| smartva_pending | <2h | >6h | >24h |
| ready_for_coding | <48h | >48h | >7d |
| coding_in_progress | <1h | >2h | >24h |
| coder_step1_saved | <4h | >24h | >7d |
| coder_finalized | <24h (recode window) | >24h | >7d |
| reviewer_eligible | indefinite (optional) | N/A | N/A |
| reviewer_coding_in_progress | <4h | >24h | >7d |
| finalized_upstream_changed | <48h | >48h | >7d |

- Terminal states excluded: reviewer_finalized, not_codeable_by_coder, not_codeable_by_data_manager, consent_refused
- Response: `alerts[]` with `state`, `label`, `total`, `gt_48h`, `gt_7d`, `p50_age_hours`, `alert_level` (normal/warning/critical/info), `dm_action`
- Special: coder_finalized includes `within_24h` and `gt_24h` split (24h recode window is normal)
- Rendering: Alert table with traffic-light color coding
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/stagnation`
- Time Frame: Snapshot

**D-WF-04: Daily State Transitions**
- Definition: How many submissions entered each state per day over the trailing window
- Extends C-19 (which only tracks smartva_completed vs coder_finalized) to ALL states
- Source: `va_submission_workflow_events` GROUP BY DATE(event_created_at), current_state
- Response: `days[]` with `date`, `transitions` (dict of state→count), `total`
- Rendering: Stacked bar chart (Chart.js), one bar per day, stacked by target state, color-coded by phase
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/daily-transitions?days=7`
- Time Frame: 7d (configurable up to 90d)

### Exclusion Details

**D-QG-01: Coder Not-Codeable Count & Rate**
- Numerator: COUNT where `workflow_state = 'not_codeable_by_coder'`
- Denominator: COUNT of CODING-POOL
- Rate: N/D × 100
- Time Frames: Today, 7d, cumulative

**D-QG-02: DM Not-Codeable Count & Rate**
- Numerator: COUNT where `workflow_state = 'not_codeable_by_data_manager'`
- Denominator: COUNT of ALL-SYNCED
- Rate: N/D × 100
- Time Frames: Today, 7d, cumulative

**D-QG-03: Exclusions by Actor**
- Definition: COUNT grouped by actor type:
  - DM: `va_data_manager_review` where `va_dmreview_status = 'active'`
  - Coder: `va_coder_review` where `va_creview_status = 'active'`
  - Reviewer rejection: `va_reviewer_review` where `va_rreview = 'rejected'` (quality signal, not workflow state)
  - Screening rejected: workflow events with `transition_id = 'screening_rejected'`
- Time Frames: Cumulative

**D-QG-04: Coder Not-Codeable Reason Breakdown**
- Numerator: COUNT grouped by `va_creview_reason`
- Values: `narration_language`, `narration_doesnt_match`, `no_info`, `others`
- Where: `va_creview_status = 'active'`
- Time Frame: Cumulative

**D-QG-05: DM Not-Codeable Reason Breakdown**
- Numerator: COUNT grouped by `va_dmreview_reason`
- Values: `submission_incomplete`, `source_data_mismatch`, `duplicate_submission`, `language_unreadable`, `others`
- Where: `va_dmreview_status = 'active'`
- Time Frame: Cumulative

**D-QG-06: ODK Has Issues Count**
- Numerator: COUNT where `va_odk_reviewstate = 'hasIssues'`
- Denominator: ALL-SYNCED
- Time Frame: Cumulative

**D-QG-07: NQA Completion Rate**
- Numerator: COUNT of submissions with at least one active `va_narrative_assessments` row (where `va_nqa_status = 'active'`)
- Denominator: COUNT of CODED submissions WHERE project `narrative_qa_enabled = true`
- Rate: N/D × 100
- Inclusions: Only projects where `narrative_qa_enabled = true`
- Exclusions: Projects where `narrative_qa_enabled = false` (excluded from both N and D)
- Time Frame: Cumulative

**D-QG-08: Social Autopsy Completion Rate**
- Numerator: COUNT of submissions with at least one active `va_social_autopsy_analyses` row (where `va_saa_status = 'active'`)
- Denominator: COUNT of CODED submissions WHERE project `social_autopsy_enabled = true`
- Rate: N/D × 100
- Inclusions: Only projects where `social_autopsy_enabled = true`
- Exclusions: Projects where `social_autopsy_enabled = false`
- Time Frame: Cumulative

**D-QG-09: Coder-Reviewer Disagreement Rate**
- Numerator: COUNT of submissions where `va_reviewer_final_assessments` exists AND `va_final_assessments` exists AND they have different `va_conclusive_cod` values
- Denominator: COUNT of submissions with both coder final assessment AND reviewer final assessment (active)
- Rate: N/D × 100
- Source: `va_final_assessments` JOIN `va_reviewer_final_assessments` on `va_sid`
- Time Frame: Cumulative

### Language Coverage Details

**D-LC-01: Submission Language Distribution**
- Numerator: COUNT grouped by `va_narration_language`
- Denominator scope: CONSENT-VALID
- Where: `va_narration_language IS NOT NULL`
- Time Frame: Cumulative
- Also report: Trend over time (monthly)

**D-LC-02: Coder Language Pool**
- Definition: Per project, list each active coder and their `vacode_language` array (exploded)
- Source: `va_users` JOIN `va_user_access_grants` (role='coder', grant_status='active')
- Time Frame: Cumulative (changes infrequently)

**D-LC-03: Language Gap Analysis**
- Definition: Set of languages present in D-LC-01 that have zero matching active coders (from D-LC-02) for the same project scope
- Numerator: For each gap language, COUNT of submissions in that language with `workflow_state IN ('ready_for_coding', 'coding_in_progress', 'coder_step1_saved')`
- Time Frame: Cumulative

**D-LC-04: Coder Output by Language**
- Numerator: COUNT of `va_final_assessments` (active) grouped by (`va_finassess_by`, `va_submissions.va_narration_language`)
- Denominator scope: CODED
- Time Frames: 7d, cumulative
- Sliceable by: coder, language, project, site

**D-LC-05: Language-Not-Codeable Correlation**
- Numerator: COUNT of `va_coder_review` where `va_creview_reason = 'narration_language'` AND submission's `va_narration_language` is in the gap set (D-LC-03)
- Denominator: COUNT of all `va_coder_review` where `va_creview_reason = 'narration_language'`
- Rate: N/D × 100
- Time Frame: Cumulative

**D-LC-06: Coder Roster**
- Definition: Per project, for each active coder: name, email, `vacode_language` list, total forms coded (cumulative), currently allocated count, active since date
- Source: `va_users` JOIN `va_user_access_grants` JOIN `va_final_assessments` COUNT
- Time Frame: Cumulative
- Note: Policy-only definition, not a dashboard widget

**D-LC-07: Forms with Missing/Unmapped Language**
- Numerator: COUNT where `va_narration_language IS NULL OR va_narration_language = '' OR va_narration_language NOT IN (SELECT alias FROM map_language_aliases)`
- Denominator: COUNT of CODING-POOL
- Rate: N/D × 100
- Scope: CODING-POOL
- Time Frame: Snapshot
- Actionable: These forms cannot be language-matched to coders. Either the ODK form doesn't collect language, the value isn't in the alias mapping table, or the field is blank. DM action: check alias mapping, update ODK form, or manually assign language

### Project × Site Details

**D-PS-01: Project-wise Form Counts**
- Definition: Per `project_id`, same columns as daily grid but aggregated at project level
- Columns: Total, Coded, Pending, Consent Refused, Not Codeable (DM + Coder), NQA count, SA count
- Time Frames: Today, cumulative

**D-PS-02: Site-wise within Project**
- Definition: Per `(project_id, site_id)`, same as D-PS-01
- Time Frames: Today, cumulative

**D-PS-03: Project Feature Summary**
- Per project: `narrative_qa_enabled`, `social_autopsy_enabled`, `coding_intake_mode`, `demo_training_enabled`, count of active coders, count of active reviewers
- Source: `va_project_master` JOIN `va_user_access_grants` COUNT
- Time Frame: Snapshot

---

## Daily Operations Grid (DM's Primary View)

The daily grid (C-01) is the landing view:

| Date | Total | New from ODK | Updated in ODK | Coded | Pending | Consent Refused | Not Codeable |
|------|-------|-------------|----------------|-------|---------|-----------------|--------------|
| Today | 1,281 | +8 | +2 | 5 | 115 | 2 | 1 |
| Yesterday | 1,273 | +12 | +1 | 9 | 108 | 1 | 3 |
| ... | ... | ... | ... | ... | ... | ... | ... |
| 7 days ago | 1,190 | +10 | +3 | 7 | 82 | 1 | 1 |

Below the grid: KPI cards for C-02 through C-22 (sync status, rates, aging, time-to-code, % reviewed, upstream changes, language gap, burndown, site bottleneck).

---

## Display Architecture

### API-Driven, Async, Bookmarkable

All dashboard data loaded via async API calls. No full-page reloads for filter changes.

**URL-based filter state (bookmarkable):**
```
/data-management/?project=UNSW01&site=KA01&lang=Hindi&range=7d
```

Every filter change updates the URL query string. Users can bookmark, share links, and navigate back.

**Filter persistence:**
- URL query string is the source of truth
- localStorage caches last-used filters as fallback (when no query string)
- Page load: read URL params → populate filter controls → trigger API calls

### Fly-out Filter Panel

A slide-out panel (offcanvas) triggered by a filter icon in the page header:

```
┌──────────────────────────────────┐
│  FILTERS                         │
│                                  │
│  Date Range                      │
│  ┌──────────────────────────┐   │
│  │ [Today ▼]  ── to ──      │   │
│  │ Quick: Today|7d|30d|All  │   │
│  └──────────────────────────┘   │
│                                  │
│  Projects & Sites                │
│  ☑ UNSW01                       │
│    ☑ NC01  ☑ KA01               │
│    ☑ KL01  ☑ TR01               │
│  ☑ ICMR01                       │
│    ☑ NC02                       │
│                                  │
│  Language                        │
│  ☑ Hindi                        │
│  ☑ Malayalam                    │
│  ☑ Tamil                        │
│  ☑ Kannada                      │
│                                  │
│  Workflow State                  │
│  ☑ All / None toggle            │
│  ☐ consent_refused              │
│  ☑ ready_for_coding             │
│  ☑ coding_in_progress           │
│  ...                            │
│                                  │
│  [Apply]  [Reset]  [Bookmark]   │
└──────────────────────────────────┘
```

- Project checkboxes auto-populate site checkboxes (expand/collapse)
- Date range: dropdown quick-picks + custom date picker
- Language checkboxes: only languages present in the filtered scope
- Workflow state: select/deselect individual states or toggle all
- Apply button: updates URL, triggers async API calls, closes panel
- Bookmark button: copies current URL to clipboard

### API Endpoints

All KPI data served through JSON API endpoints:

| Endpoint | Returns | Method |
|----------|---------|--------|
| `GET /api/v1/data-management/kpi` | KPI card counts (C-02 to C-22) | Async, cached 5 min |
| `GET /api/v1/data-management/daily-grid` | Daily operations grid rows | Async, from `va_daily_kpi_aggregates` |
| `GET /api/v1/data-management/project-site-submissions` | PS-01/PS-02 matrices | Async |
| `GET /api/v1/data-management/filter-options` | Available filter values (projects, sites, languages, states) | Async |
| `GET /api/v1/data-management/language-gap` | Language gap analysis (D-LC-03, C-20) | Async |
| `GET /api/v1/data-management/exclusion-breakdown` | Reason breakdowns (D-QG-04, D-QG-05) | Async |
| `GET /api/v1/data-management/coder-stats` | Coder utilization + output (C-21, D-LC-04) | Async |
| `GET /api/v1/data-management/burndown` | Predicted vs achieved time-series (C-18) | Async |
| `GET /api/v1/data-management/submissions` | Paginated submission table (existing) | Async, infinite scroll |

All endpoints accept query parameters matching the filter dimensions (`project`, `site`, `lang`, `range`, `state`).

### Progressive Loading

1. **Immediate:** Page shell + cached KPI cards render from localStorage
2. **Fast (<500ms):** KPI card counts load from API (MV-backed, cached)
3. **Medium (<2s):** Daily grid, charts load from daily aggregates
4. **Slow (<5s):** Detailed breakdowns, language gap, coder stats
5. **On-demand:** Sync preview (live ODK call), CSV exports

### Export

- **CSV export** of daily grid, project/site matrix, language gap table
- **Print view** of the dashboard (CSS @media print)
- All exports respect current filter state

---

## MV Enhancement Appendix

Potential MV improvements noted for future implementation:

1. **Add `va_narration_language` to demographics MV** — for D-LC-01, D-LC-03, D-LC-04
2. **Denormalize project feature flags** — `narrative_qa_enabled`, `social_autopsy_enabled` for D-QG-07, D-QG-08
3. **`va_daily_kpi_aggregates` table** — pre-computed daily grid (defined above)
4. **Not-codeable reason in MV** — for D-QG-04, D-QG-05 breakdowns without review-table joins
5. **Coding duration pre-computation** — store min/max/p50/p90 in daily aggregates

---

## Files

### Create
- `docs/policy/kpis.md`

### Reference
- `app/services/workflow/definition.py` — canonical states and transitions
- `app/models/va_sync_runs.py` — sync run model
- `app/models/mas_languages.py` — language models
- `app/forms/va_coderreview_form.py` — coder not-codeable reasons
- `app/forms/va_datamanagerreview_form.py` — DM not-codeable reasons
- `app/models/va_narrative_assessments.py` — NQA model
- `app/models/va_social_autopsy_analysis.py` — social autopsy model
- `app/models/va_project_master.py` — project feature flags
- `app/services/submission_analytics_mv.py` — current MV definitions
- `docs/policy/data-manager-workflow.md` — existing DM policy
- `docs/policy/coding-workflow-state-machine.md` — workflow state machine

## Verification

- [ ] YAML frontmatter valid
- [ ] DM scoping rules documented
- [ ] KPI storage model defined (hybrid: daily aggregates + event-sourced)
- [ ] Hard gates with 4 denominator scopes and inclusion/exclusion rules
- [ ] Time frames on every KPI
- [ ] Core (~15) + Detailed (~25) split
- [ ] Every KPI has exact numerator/denominator with inclusion/exclusion rules
- [ ] Daily operations grid with 7 columns defined
- [ ] Time to Code with min/max/median/P90
- [ ] % Forms Reviewed with 24h recode window exclusion
- [ ] % Uncoded, % Not Codeable, % Upstream Changes
- [ ] Reopen Rate in Detailed
- [ ] Not-codeable reasons match form choices
- [ ] Reviewer rejection described as quality signal
- [ ] NQA/SA linked to project flags with exclusion rules
- [ ] MV enhancement appendix included
- [ ] Cross-references existing policy docs
