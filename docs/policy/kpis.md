---
title: Data Manager KPI Framework
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-27
---

# Data Manager KPI Framework

> **Implementation plans:** [`.tasks/kpis-policy.md`](../../.tasks/kpis-policy.md), [`.tasks/digitva-r5s0-kpi-registry-plan.md`](../../.tasks/digitva-r5s0-kpi-registry-plan.md) (core, registered, registry and MCP) and [`.tasks/digitva-0hul-kpi-query-refresh.md`](../../.tasks/digitva-0hul-kpi-query-refresh.md) (audit of the queries)

## Context

Project-site data managers need a systematic, measurable KPI framework to monitor DigitVA system performance. This document gives a precise definition for every KPI: exact numerator and denominator, with inclusion and exclusion rules, so they can be measured and compared.

### Core panels and registered KPIs (owner decision 2026-10-27, `digitva-r5s0`)

A small, accurate and meaningful pool beats a wide, inconsequential one, and as many KPIs as possible are retained. Every KPI therefore has one of four tiers:

- **Core panels (18):** the KPIs with a fixed panel on the dashboard. These are fixed, tested and shown by default.
- **Registered KPIs (35):** queryable by id on the dashboard, in the registry and over MCP, with no fixed panel.
- **Merged (16):** the id still resolves, but the measure is now a `by=` or a `view=` of a core or registered KPI. The definition is kept under the surviving KPI.
- **Retired:** not a measure (the four stored-aggregate groups and D-PS-03). Each has a one-line reason.

This replaces the earlier "Core (~15) / Detailed (~25)" split and the card list. KPIs are grouped by results-chain stage (input, process, output, outcome) and then by category. The classification fields are below.

| Tier | Input | Process | Output | Outcome | Total |
|---|---|---|---|---|---|
| Core | 2 | 7 | 5 | 4 | 18 |
| Registered | 2 | 16 | 15 | 2 | 35 |
| Merged | 2 | 6 | 8 | 0 | 16 |
| Retired | 0 | 4 stored-aggregate groups | 1 (D-PS-03) | 0 | 1 id + 4 groups |

Registered Process holds the 13 earlier KPIs plus CL-01, CL-02 and CL-04. Registered Output holds 14 plus CL-03. The merged total of 16 ids is the plan's 18 minus two rows that never had an id (the daily-grid Pending column, now C-04, and the "SmartVA failed" row, now a C-23 row).

### Classification fields

Every KPI carries these fields, and the registry (`app/data/kpi_registry.json`) stores the same ones.

| Field | Values |
|---|---|
| **stage** | input, process, output, outcome |
| **category** | workforce, flow, timeliness, coding quality, system, loop, coverage, data quality, equity, cause mix |
| **type** | rate, volume, duration, gap, net, aged volume, distribution, matrix, roster |
| **level** | Pj project, St site (project-site pair), Dt district, Bk block, Fu facility unit (CHC, PHC, SC), Sys system (ODK sync, SmartVA queue; not per unit) |
| **audience** | DM, admin (the in-charge and field team appear as blocker owners) |
| **cadence** | snapshot, daily, weekly, monthly, on demand |
| **views** | status, trend, forecast, blocker, critical path (see "Analytic views") |
| **tier** | core, registered, merged, retired |


**Shared rules for every core KPI** (owner decision 2026-10-27, `digitva-r5s0`):

- **Scope:** `DmScope.sql()`, counting a pair or unit subtree once, with confirmed duplicates excluded and training excluded.
- **Peers:** siblings inside the viewer's grant only (see "Peer comparison").
- **Rates and ranks:** shown only when the denominator is 20 or more (`PERCENT_MIN_WHOLE`).
- **Small cells:** any count under 5 is folded.
- **Canonical terms:** as defined under "Canonical definitions".
- **Death-register projects only:** AD-COV, AD-VN and the register half of EQ-02 apply to death-register projects only. Other projects do not compute them.


---

## DM Scoping Rules

A data manager's visibility is determined by their grants in `va_user_access_grants`:

- **Project-level grant** (`scope_type = 'project'`): DM sees all sites within that project.
- **Project-site grant** (`scope_type = 'project_site'`): DM sees only that specific project-site pair.
- A single DM may hold multiple grants across different projects and project-site pairs.
- **Every KPI denominator is filtered through the DM's scope** (`dm_kpi_scope.DmScope`, built from the authorization module's resolved grants) — a DM only sees data for the projects, sites and unit subtrees they have grants for.
- When the dashboard shows project-level or site-level breakdowns, it only shows projects/sites within the DM's scope.
- A submission is attributed to its form's own `(project_id, site_id)` pair. A site may be active in several projects; analytics never re-attributes a submission to another project sharing the site. See [Project attribution](../current-state/submission-analytics.md#project-attribution).

---

## KPI Storage: Live From Workflow Events (owner decision 2026-10-27, `digitva-0hul`)

### Canonical definitions (owner decision 2026-10-27, `digitva-0hul`)

Every KPI uses these definitions; none is redefined per KPI.

| Term | Definition |
|------|-----------|
| **Pending** | The 6 states of the `awaiting_coding` and `in_coding` buckets of `WORKFLOW_CODING_BUCKETS` in `app/services/workflow/definition.py`: `screening_pending`, `attachment_sync_pending`, `smartva_pending`, `ready_for_coding`, `coding_in_progress`, `coder_step1_saved`. Exposed as `PENDING_STATES`, derived from the buckets, never retyped. |
| **Ready pool** | `ready_for_coding` only (`CODER_READY_POOL_STATES`). Used where a case can be handed to a coder now: C-07 aging and the language-gap alert. |
| **Blocked** | Pending and blocked, plus the upstream states (`finalized_upstream_changed`, split into ODK change and sent back for revision), counted in one query. |
| **Coded** | As a state: the `coded` bucket. As output: non-demo finalize events (`coder_finalized`, `recode_finalized`). |
| **Time to code** | Each finalize event paired with the latest start before it, `coding_started` or `recode_started`. |
| **Inflow / outflow** | Cases crossing the pending boundary: inflow enters the pending set, outflow leaves it. Replaces the former event list (`sync_new_payload_routed`, `smartva_completed`). |
| **Coder availability** | Coders who can code at least one case in the DM's subtree, with `lower(trim())` language matching; a coder with no languages covers any language. See C-21 and [Access Control Model](access-control-model.md). |
| **Demo** | One shared predicate drops demo events from output and rate KPIs. Demo projects stay in scope. See "Demo exclusion" below. |

### Aggregates are retired as a read source (owner decision 2026-10-27, `digitva-0hul`)

KPIs are computed live from `va_submission_workflow_events` and the
submission tables. `va_daily_kpi_aggregates` is no longer read by any KPI. The
table and model stay in the schema for now; nothing schedules, backfills or
refreshes it, and its commands and write hooks are removed (`digitva-0hul`,
step 2). The old table was keyed `(snapshot_date, site_id)`, not
`(snapshot_date, project_id, site_id)`, mixed web and ODK intake and stored the
current state on past dates, which is why it is retired rather than repaired.

End-of-day state for any past day `d` is rebuilt from the events' `previous_state`
and `current_state`:

`count_P(end of d) = count_P(now) - sum over events after d of ([current_state in P] - [previous_state in P])`

where `P` is the pending set (or any other state set). This gives viewer-timezone
days, unit subtrees and per-project recode windows without a stored series.
A stored series is reconsidered only if `EXPLAIN (ANALYZE, BUFFERS)` of the
burndown from project start misses its budget at production size.

### App-Level Settings

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `project_target_completion_date` | DATE (per project) | NULL | Target date for completing all coding. Enables predicted-vs-achieved charts. |

The `daily_kpi_aggregation_timezone` and `daily_kpi_aggregation_time` settings
are removed (owner decision 2026-10-27, `digitva-0hul`): they were never implemented and there is no snapshot task to
time. **Days follow the viewer's timezone** (`user.timezone`, default
`Asia/Kolkata`), applied at query time. Coding gates, allocation windows and
recode windows stay on UTC. Do not use `va_local_date` on `event_created_at`.

### Demo exclusion (owner decision 2026-10-27, `digitva-0hul`)

Demo events are dropped from output and rate KPIs (coded, throughput, coding
rate, time to code, inflow/outflow, burndown achieved) with one shared
predicate: the project is not `demo_training_enabled` and the submission has
no `demo_started` event. State-based KPIs (C-04, C-05, the flowchart) are
unchanged, since they report the cases' real states. Demo exclusion applies to event-based KPIs only; the outcome, equity and coverage KPIs (O-UNK, D-QG-09, EQ-01, EQ-02, AD-FCOD, AD-COV) and the critical-path end segments do not apply it. Data managers of a demo
project still see the project in scope.

### Intake source (owner decision 2026-10-27, `digitva-0hul`)

"New" counts created submissions (ODK and web intake), not
`va_sync_runs.records_added`. C-13 and C-14 are ODK-only: web intake has no ODK
submission time and no Central attachments, so they filter `va_forms.form_source = 'odk'`.

### Recode window (owner decision 2026-10-27, `digitva-0hul`)

Wherever a KPI mentions the recode window it is the project's
`recode_window_minutes` (`app/services/recode_window.py`), not a fixed 24 h. The
API returns `within_window` / `beyond_window` and keeps `within_24h` /
`beyond_24h` for one release beside them for the Expo client.

### Peer comparison (owner decision 2026-10-27, `digitva-0hul`)

A KPI marked as comparable may be compared across **siblings inside the
viewer's grant**: a project view compares districts, a district view compares
blocks or CHCs, a CHC view compares PHCs. Never a unit with a different level,
never siblings above the viewer's grant (a grant confers nothing above its
unit). Rates and ranks appear only for a peer with at least 20 cases
(`PERCENT_MIN_WHOLE` in `app/services/area_dashboard_service.py`); below that the
count is shown without a rate or rank. Peer output is counts and rates only, no
PII. A case routed to two nested granted units counts once.

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
| **ALL-SYNCED** | Every row in `va_submissions` within DM scope that is still in ODK | All submissions, all states | `va_sync_issue_code = 'missing_in_odk'` (see below) |
| **CONSENT-VALID** | ALL-SYNCED minus consent_refused | Everything except consent=no | `workflow_state = 'consent_refused'` only |
| **CODING-POOL** | CONSENT-VALID minus DM-not-codeable | Submissions that entered or could enter coding | `consent_refused`, `not_codeable_by_data_manager` |
| **CODED** | Submissions that reached coder_finalized or beyond | `coder_finalized`, `reviewer_eligible`, `reviewer_coding_in_progress`, `reviewer_finalized`, `finalized_upstream_changed` | Everything else |

**Retired from ODK is a scope-wide exclusion.** A submission whose
`va_sync_issue_code` is `missing_in_odk` no longer exists in ODK Central
([ODK Retired Submissions Policy](odk-retired-submissions.md)). It is kept with
all of its history but is excluded **by default** from every scope above, and
therefore from every KPI, the KPI daily grid, analytics MV consumers, COD
bucket and Site PI reporting, and all exports. Mechanically the core analytics
MV carries an `odk_missing` boolean and consumers filter `odk_missing = false`;
the rows stay in the MV. The data-manager submission list defaults to the *In
sync* filter and still offers *Missing in ODK* and *All*.

The one KPI that counts them is **D-SH-03** below, so the gap between DigitVA
and Central is always visible rather than silently absorbed.

Every endpoint group under `app/routes/api/dm_kpi/` applies the exclusion in
its live SQL, through the shared predicate in
[`app/services/odk_retirement_service.py`](../../app/services/odk_retirement_service.py)
(`in_odk_sql(alias)` + `IN_ODK_BIND` for `sa.text()` queries,
`submission_is_in_odk()` for Core expressions) placed in the WHERE clause
closest to `va_submissions`, so joined aggregates over events, allocations and
assessments are filtered through the submission rather than after aggregation:

| Endpoint group | KPIs | Retired rows |
|---|---|---|
| `dm_kpi_grid` | C-01 daily grid (live) | excluded |
| `dm_kpi_pipeline` | C-04, C-07, C-08, C-09, C-10, C-11, C-19, C-22, D-WT-01…04 | excluded |
| `dm_kpi_workflow` | D-WF-01…04 | excluded |
| `dm_kpi_exclusions` | C-05, C-06, C-23, D-QG-01…08 | excluded |
| `dm_kpi_coders` | C-12, C-21, C-24, D-LC-04, D-LC-06, D-QG-09 | excluded |
| `dm_kpi_language` | C-15, C-20, D-LC-01, D-LC-03, D-LC-07 | excluded |
| `dm_kpi_burndown` | C-16, C-17, C-18 | excluded |
| `dm_kpi_sync` | C-13, C-14 | excluded (see below) |
| `dm_kpi_sync` | C-02, C-03, D-SH-01, D-SH-04 | not applicable (see below) |

**Per-KPI decisions for the sync group.** Sync KPIs are the one place where
"the whole synced population" could plausibly mean *including* retired rows, so
each was decided from its own definition:

- **C-13 Sync Latency** — excluded. Its denominator is ALL-SYNCED, and
  ALL-SYNCED is defined above as the rows still in ODK. A retired submission's
  latency describes a sync that is no longer live.
- **C-14 Attachment Health** — excluded. A retired submission's local
  attachments are the archival copy and Central has usually purged the source
  ([ODK Retired Submissions Policy](odk-retired-submissions.md)), so counting
  it as a missing-attachment defect would report a gap no DM can close.
- **C-02 Last Sync Run Status**, **C-03 Sync Error Rate**, **D-SH-01
  Attachment Download Completeness** — not applicable: counted over
  `va_sync_runs` rows, not over submissions.
- **D-SH-04 SmartVA Failure Rate** — not applicable: counted over
  `va_smartva_runs` rows, not over submissions.
- **D-SH-03 Locally Missing in ODK** — the deliberate exception; it counts
  retired submissions and is served from the core analytics MV, not from this
  package.

**Key distinction:**
- **Hard gate** (`consent_refused`): permanent, excluded from all downstream scopes
- **Soft gates** (`not_codeable_by_data_manager`, `not_codeable_by_coder`): reversible. ODK data updates or admin override can return these forms to the pipeline. These should be tracked and surfaced to the DM as "actionable" rather than "lost."

---

## Time Frames

| Frame | Definition |
|-------|-----------|
| **Today** | Since midnight in the viewer's timezone (default Asia/Kolkata) (owner decision 2026-10-27, `digitva-0hul`) |
| **Yesterday** | Previous calendar day |
| **Last 7 days** | Rolling 7 calendar days including today |
| **Cumulative** | All-time since first submission in scope |

---

## Core panels (18)

Grouped by stage, then category. Each heading carries the question, the classification, the level, scope and peer rule, the direction and threshold, the views and the definition.

**Input** (what the programme has to work with: people and languages.) Categories: workforce.

### C-21: Coder Utilization Rate

**Question:** Do we have enough coders, and are they busy?
- **Classification:** Input / workforce / rate; tier core; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Dt Bk Fu; scope coders who can code a case in the DM's subtree (coder availability); peers: Yes, siblings inside the grant.
- **Direction and threshold:** Band: below 70% means idle coders, above 95% means saturated.
- **Views:** status, trend (needs grant and allocation history checked first).
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of coders with at least one active allocation (`va_allocations` where `va_allocation_status = 'active'`)
- **Denominator:** COUNT of coders who can code at least one case in the DM's subtree (owner decision 2026-10-27, `digitva-0hul`): project grants, grants on in-scope (project, site) pairs, and unit grants that are ancestors or descendants of the DM's unit, excluding ancestors above `coding_scope_level_id` when the project is `view_only`. For a project or site DM this equals all active coders of its scope. See [Access Control Model](access-control-model.md).
- **Rate:** N / D × 100
- **Time Frame:** Snapshot
- **Actionable:** If utilization is low (<70%), coders are idle — either not enough forms in their language or forms aren't being allocated. If high (>95%), coders are saturated — need more coders.

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**D-LC-02: Coder Language Pool** (merged as `by=language` (counts; names stay in D-LC-06))

- Definition: Per project, list each active coder and their `vacode_language` array (exploded)
- Source: `va_users` JOIN `va_user_access_grants` (role='coder', grant_status='active')
- Time Frame: Cumulative (changes infrequently)


### C-15: Language Gap Alert

**Question:** Which ready cases have no coder for their language?
- **Classification:** Input / workforce / gap; tier core; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Dt Bk Fu; scope ready pool; coders by coder availability; peers: Cases follow unit grants; coders counted for the subtree. Not ranked.
- **Direction and threshold:** Lower is better; 0 expected.
- **Views:** status, blocker.
- **MCP:** full.

**Definition:**

- **Definition:** COUNT of submissions in the ready pool (`ready_for_coding`) (owner decision 2026-10-27, `digitva-0hul`) where `va_narration_language` has zero available coders. A coder matches when `lower(trim(language))` equals `lower(trim(va_narration_language))`; a coder with no languages matches any language. Coders are counted for the DM's subtree (coder availability).
- **Source:** `va_submissions` JOIN `va_users.vacode_language` via grants
- **Scope:** ready pool
- **Time Frame:** Snapshot
- **Drill-down:** Which languages, how many submissions affected

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**D-LC-03: Language Gap Analysis** (merged as `by=language`)

- Definition: Set of languages present in D-LC-01 that have zero matching active coders (from D-LC-02) for the same project scope
- Numerator: For each gap language, COUNT of submissions in that language in the ready pool (`ready_for_coding`) (owner decision 2026-10-27, `digitva-0hul`), with the same case-insensitive, trimmed language matching and coder availability as C-15
- Time Frame: Cumulative


**Process** (how cases move: flow, timeliness, coding quality, system health and the correction loop.) Categories: flow, timeliness, system.

### C-04: % Uncoded (Pending Rate)

**Question:** How much is uncoded, and when will it clear?
- **Classification:** Process / flow / rate and days; tier core; audience DM, admin; cadence snapshot, daily.
- **Level, scope and peers:** Pj-St, plus child units; scope CODING-POOL; pending set; peers: Yes: districts in a project view, child units in an organization project.
- **Direction and threshold:** Lower is better. Days to clear above 30 means more coders or faster coding are needed.
- **Views:** status, trend, forecast.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT in the 6 pending states (`screening_pending`, `attachment_sync_pending`, `smartva_pending`, `ready_for_coding`, `coding_in_progress`, `coder_step1_saved`) (owner decision 2026-10-27, `digitva-0hul`)
- **Denominator:** COUNT of CODING-POOL
- **Rate:** N / D × 100
- **Scope:** CODING-POOL
- **Time Frames:** Snapshot, also daily in grid
- **Meaning:** What fraction of the eligible pipeline has NOT been coded yet

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**C-17: Predicted Days to Clear Backlog** (merged as `view=forecast`)

- **Definition:** Estimated days to code all currently uncoded forms in the pipeline
- **Formula:** `pending_count (C-04 numerator) / mean_daily_coding_rate (C-16)`
- **Scope:** CODING-POOL
- **Time Frame:** Snapshot (recalculated daily)
- **Also report:** Per-language prediction: pending_in_language_X / daily_rate_language_X
- **Actionable:** If predicted days > 30, the DM knows they need more coders or the current coders need to accelerate
- **Edge case:** If mean_daily_coding_rate = 0 (no coding in 7d), report "∞" or "N/A"

**C-22: Site-Level Bottleneck** (merged as `by=unit` (peer view))

- **Definition:** Per site: `(pending_count / total_count) × 100` — the % of a site's submissions that are still uncoded, with pending = the 6 pending states (owner decision 2026-10-27, `digitva-0hul`)
- **Display:** Table ranked by % uncoded DESC. In an organization project the rows are the viewer's child units (peer comparison, above) rather than the single automatic site
- **Scope:** CODING-POOL, grouped by site (sites project) or by child unit (organization project)
- **Time Frame:** Snapshot
- **Actionable:** The site at the top of this list is the bottleneck. DM can investigate: is that site getting more submissions? Does it have fewer coders? Are forms harder to code?

**D-WT-03: Coding Backlog Trend** (merged as `view=trend`)

- Definition: Daily time-series of COUNT in the 6 pending states (owner decision 2026-10-27, `digitva-0hul`), end-of-day state rebuilt from events (the stored series mixed 6 states with a 1-state live "today")
- Source: `va_submission_workflow_events` (`previous_state`, `current_state`)
- Display: Line chart, default 90-day window


### C-19: Daily Inflow vs Outflow

**Question:** Are we keeping up (inflow against outflow)?
- **Classification:** Process / flow / net; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj Dt Bk Fu; scope crossings of the pending boundary; peers: Yes.
- **Direction and threshold:** Net inflow minus outflow above 0 means falling behind; below 0 means catching up.
- **Views:** trend, forecast.
- **MCP:** full.

**Definition:**

- **Inflow:** COUNT of events that day whose `previous_state` is outside the pending set and `current_state` is inside it (owner decision 2026-10-27, `digitva-0hul`), so a case entering through SmartVA failure, a reset or an admin override counts too
- **Outflow:** COUNT of non-demo events that day whose `previous_state` is pending and `current_state` is not (cases leaving the pending set, which includes finalizing); demo events excluded
- **Net delta:** Inflow − Outflow
- **Display:** Side-by-side bar chart (inflow vs outflow per day, last 7d)
- **Actionable:** If inflow consistently exceeds outflow, backlog will grow. Positive net delta = falling behind. Negative = catching up.

### C-23: Blocked Forms Alert (Composite)

**Question:** What is stopping cases, why, how old, and who can unblock them?
- **Classification:** Process / flow / volume; tier core; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Pj Dt Bk Fu; scope blocked set (pending plus upstream); peers: Yes.
- **Direction and threshold:** Lower is better; 0 expected. Each row names an owner (see below).
- **Views:** blocker, status.
- **MCP:** full.

**Definition:**

- **Definition:** COUNT and breakdown of all submissions that cannot be routed to a coder right now, grouped by blockage reason (owner decision 2026-10-27, `digitva-0hul`). Every row except the two upstream rows is restricted to the 6 pending states, so a coded case with a flagged ODK review state or a missing language is not blocked. The upstream rows are coded cases waiting on a DM and stay in the total. One `FILTER` query.
- **Breakdown:**

| Blockage Reason | Condition | DM Action Required |
|----------------|-----------|-------------------|
| Awaiting DM screening | `workflow_state = 'screening_pending'` | Pass or reject screening |
| Attachments not synced | `workflow_state = 'attachment_sync_pending'` | Trigger attachment sync |
| Missing attachments | Past SmartVA gate but `va_submission_attachments` count = 0 | Re-trigger attachment sync; check ODK Central |
| SmartVA not run | `workflow_state = 'smartva_pending'` | Check SmartVA queue |
| Upstream change pending | `workflow_state = 'finalized_upstream_changed'`, latest event not a revision request | Accept or reject upstream change |
| Sent back for revision | `workflow_state = 'finalized_upstream_changed'`, latest event a send-back or reopen | Wait for the interviewer or cancel the request |
| Missing language | `va_narration_language IS NULL/empty` | Fix language mapping |
| Unmapped language | `va_narration_language NOT IN (SELECT alias FROM map_language_aliases)` | Add alias mapping |
| Language gap | Language has zero coders | Recruit/reassign coders |
| ODK flagged | `va_odk_reviewstate = 'hasIssues'` | Coordinate with field team |

- **Overlap handling:** A single submission may have multiple conditions (e.g., not-codeable AND ODK-has-issues). The breakdown counts each condition independently (a form can appear in multiple rows). A separate "total blocked" count deduplicates by counting each form once, assigned to its **primary blockage** (highest-priority condition in the order listed above).
- **Display:** Table showing blockage type + count + action. Total blocked count shown separately.
- **Scope:** pending states plus the upstream states (excludes `consent_refused` — that's a hard gate)
- **Note on soft gates:** `not_codeable_by_data_manager` and `not_codeable_by_coder` forms are excluded from CODING-POOL but tracked separately in C-05/D-QG-01/D-QG-02. They are NOT double-counted here. However, if ODK data updates and makes a not-codeable form potentially codeable, it would re-enter the screening pipeline.
- **Time Frame:** Snapshot
- **Actionable:** This is the DM's "to-do list" — each blockage type has a clear action. DM works through the list to unblock forms and increase throughput.

- **Owner of each blocker row** (owner decision 2026-10-27, `digitva-r5s0`):
  - screening, upstream change and the soft gates: the DM;
  - attachment sync and SmartVA: the DM, or admin when the queue is down;
  - language gap and "no coder at unit": the coder supervisor or in-charge;
  - sent back and ODK flagged: the field team, through the IC.
- **Sent back** also carries the former "awaiting correction" figure: its age (p50 and max), owner ("interviewer, through the IC") and `by=interviewer` (web only). Every C-23 row gains an `intake_source` split.

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**C-10: Upstream Change Queue** (merged as the "Upstream change pending" row, `by=reason`)

- **Definition:** COUNT where `workflow_state = 'finalized_upstream_changed'` and the latest workflow event is not a send-back or reopen (ODK upstream changes only)
- **Source:** `va_submission_workflow` WHERE `workflow_state = 'finalized_upstream_changed'`, split on the latest event's `transition_reason` (`app/services/workflow/revision_request_sql.py`)
- **Companion:** `c10_sent_back_count` counts the same state when the latest event is `sent_back_for_revision` / `reopened_for_revision` (a coder or reviewer send-back, a supervisor reopen). It is a virtual state `sent_back_for_revision`, never stored
- **Scope:** CODED
- **Time Frame:** Snapshot


### C-07: Pipeline Aging (Stagnation)

**Question:** Which states hold cases too long?
- **Classification:** Process / timeliness / aged volume; tier core; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Dt Bk Fu; scope ready pool for the ready_for_coding count; every non-terminal state for the stagnation table; peers: Yes.
- **Direction and threshold:** Lower is better; per-state normal, alert and critical thresholds in the table below.
- **Views:** status, trend, blocker.
- **MCP:** full.

**Definition:**

- **Definition:** COUNT of submissions where `workflow_state = 'ready_for_coding'` AND `workflow_updated_at < now() − interval '48 hours'`
- **Also report:** Same count at thresholds: >48h, >7d, >30d
- **Source:** `va_submission_workflow` JOIN `va_forms` for scope
- **Scope:** CODING-POOL (ready pool, `ready_for_coding` only, by design)
- **Time Frame:** Snapshot

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**D-WF-03: State Stagnation Alerts** (merged as `by=state`; the threshold table is kept unchanged under C-07)

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
| coder_finalized | <recode window (project setting) | >recode window | >7d |
| reviewer_eligible | indefinite (optional) | N/A | N/A |
| reviewer_coding_in_progress | <4h | >24h | >7d |
| finalized_upstream_changed (ODK changes) | <48h | >48h | >7d |
| sent_back_for_revision (virtual: fuc whose latest event is a send-back or reopen) | <48h | >48h | >7d |

- Terminal states excluded: reviewer_finalized, not_codeable_by_coder, not_codeable_by_data_manager, consent_refused
- Response: `alerts[]` with `state`, `label`, `total`, `gt_48h`, `gt_7d`, `p50_age_hours`, `alert_level` (normal/warning/critical/info), `dm_action`
- State counts, the flowchart (`stages.upstream_changed` and `stages.sent_back`) and stagnation group by the effective state; `state-velocity` (D-WF-02) still reports raw stored states
- Special: coder_finalized includes a `within_window` and `gt_window` split using the project's recode window (owner decision 2026-10-27, `digitva-0hul`); `within_24h` and `gt_24h` stay for one release
- Rendering: Alert table with traffic-light color coding
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/stagnation`
- Time Frame: Snapshot


### C-08: Time to Code (Min / Max / Median / P90)

**Question:** How long does a coding episode take?
- **Classification:** Process / timeliness / duration; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Dt Bk Fu; scope CODING-POOL; non-demo finalize events; peers: Yes: median per unit, minimum n applies.
- **Direction and threshold:** No fixed threshold; compare against peers and own trend.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Definition:** For each finalize event in the window, compute `finalize.event_created_at − latest start.event_created_at`, where the latest start is the most recent `coding_started` or `recode_started` event at or before the finalize (owner decision 2026-10-27, `digitva-0hul`). A recoded case yields one duration per finalize, never one per start/finalize combination.
- **Aggregates:** MIN, MAX, PERCENTILE(0.5), PERCENTILE(0.90)
- **Source:** `va_submission_workflow_events` rows of the same `va_sid`, each `coder_finalized`/`recode_finalized` paired by a lateral lookup with its latest start
- **Scope:** CODING-POOL
- **Inclusions:** First-pass coding AND recode episodes
- **Exclusions:** Demo events (shared demo predicate)
- **Time Frames:** Today, yesterday, 7d

### D-WF-02: State Velocity

**Question:** Which stage dominates end-to-end time, and where is the bottleneck against peers?
- **Classification:** Process / timeliness / duration; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj Dt Bk Fu; scope workflow events by stage; peers: Yes: bottleneck is the gap to the sibling median.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** critical path, trend.
- **MCP:** full.

**Definition:**

- Definition: Average time submissions spend in each workflow state before transitioning out
- Source: CTE on `va_submission_workflow_events` computing per-transition durations, aggregated per `previous_state`
- Aggregates: AVG, P50, P90 in hours
- Response: `states[]` with `state`, `label`, `transition_count`, `avg_hours`, `p50_hours`, `p90_hours`
- Rendering: Table with sortable columns, slow states highlighted
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/state-velocity?days=30`
- Time Frame: 30d (configurable up to 90d)

### C-03: Sync Error Rate

**Question:** Is ODK sync working?
- **Classification:** Process / system / rate; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** System; scope `va_sync_runs`; peers: No.
- **Direction and threshold:** Lower error rate is better; no fixed threshold.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of `va_sync_runs` where `status IN ('error', 'partial')` and `started_at ≥ window_start`
- **Denominator:** COUNT of all `va_sync_runs` where `started_at ≥ window_start`
- **Rate:** N / D × 100
- **Time Frames:** 7d, cumulative

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**C-02: Last Sync Run Status** (merged as `view=status` (last run row))

- **Definition:** `status` from most recent `va_sync_runs` row, plus `started_at` and `finished_at`
- **Source:** `va_sync_runs` ORDER BY `started_at DESC LIMIT 1`
- **Time Frame:** Snapshot


**Output** (what the process produces: coded cases, coverage, data quality and workforce output.) Categories: flow, coverage, data quality.

### C-01: Daily Operations Grid

**Question:** What came in and what got coded each day?
- **Classification:** Output / flow / volume; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj-St; scope ALL-SYNCED for received; coded events for output; peers: No.
- **Direction and threshold:** Informational; read against C-19.
- **Views:** trend.
- **MCP:** full.

**Definition:**

A 7-column table, last 8 rows (today + 7 prior days), slicable by project and site.

| Column | Numerator | Denominator | Scope | Source |
|--------|-----------|-------------|-------|--------|
| **Total** | COUNT of ALL-SYNCED submissions created up to and including that day (cumulative, not that day's new count) | — | ALL-SYNCED | `va_submissions` |
| **New** (was New from ODK) | COUNT of submissions created that day, ODK and web intake (owner decision 2026-10-27, `digitva-0hul`) | — | ALL-SYNCED | `va_submissions` |
| **Updated in ODK** | SUM of `va_sync_runs.records_updated` for runs where `DATE(started_at) = row_date` | — | N/A | `va_sync_runs` |
| **Coded** | COUNT of non-demo `va_submission_workflow_events` where `transition_id IN ('coder_finalized', 'recode_finalized')` and the viewer-timezone date of `event_created_at` = row_date (owner decision 2026-10-27, `digitva-0hul`) | — | CODED | `va_submission_workflow_events` |
| **Pending Coding** | COUNT of the 6 pending states as of end of that day, rebuilt from events (owner decision 2026-10-27, `digitva-0hul`) | — | CODING-POOL | `va_submission_workflow` |
| **Not analysable** (was Consent Refused) | COUNT of events where `transition_id` resulting in `current_state = 'consent_refused'` and `DATE(event_created_at) = row_date` | — | ALL-SYNCED | `va_submission_workflow_events` |
| **Not Codeable** | COUNT of events where `transition_id IN ('coder_not_codeable', 'data_manager_not_codeable')` and `DATE(event_created_at) = row_date` | — | ALL-SYNCED | `va_submission_workflow_events` |

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**D-PS-01: Project-wise Form Counts** (merged as `by=project`)

- Definition: Per `project_id`, same columns as daily grid but aggregated at project level
- Columns: Total, Coded, Pending, Not analysable, Not Codeable (DM + Coder), NQA count, SA count
- Time Frames: Today, cumulative

**D-PS-02: Site-wise within Project** (merged as `by=site`)

- Definition: Per `(project_id, site_id)`, same as D-PS-01
- Time Frames: Today, cumulative


### AD-FCOD: Final Cause Coverage

**Question:** What share of codeable cases has an authoritative cause?
- **Classification:** Output / coverage / rate; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj-St; scope CODING-POOL; peers: Yes.
- **Direction and threshold:** Higher is better; the forecast is C-18.
- **Views:** status, trend, forecast.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of CODING-POOL submissions with an authoritative final cause (`va_final_cod_authority`; the WHO 2026 bucket is read from the COD snapshot MV, `authoritative_who_bucket`).
- **Denominator:** COUNT of CODING-POOL, less `not_codeable_by_coder` (the codeable cases).
- **Rate:** N / D × 100. Shown only when D is 20 or more.
- **Replaces:** the area dashboard "Final COD" column, the Site-PI "coded" count, and the "achieved" half of C-18. C-18 is the forecast of this KPI.
- **Time Frames:** Snapshot, daily series.

### AD-COV: Reported-Death Interview Coverage

**Question:** Are reported deaths being interviewed, and how many have waited over 30 days? (death-register projects only)
- **Classification:** Output / coverage / rate; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Dt Bk Fu; scope death-register cases; peers: Yes.
- **Direction and threshold:** Higher is better; the count waiting over 30 days should fall.
- **Views:** status, trend, blocker.
- **MCP:** full.

**Definition:**

- **Applies to death-register projects only** (owner decision 2026-10-27, `digitva-r5s0`). A project without a death register has no reported-death base, and the KPI is not computed for it.
- **Reported deaths:** register rows of the project, with confirmed duplicates excluded.
- **Numerator:** reported deaths that have an interview (a linked submission).
- **Denominator:** reported deaths.
- **Rate:** `rate` is interviewed ÷ reported (N / D × 100). Shown only when D is 20 or more.
- **Waiting over 30 days:** COUNT of reported deaths with no interview whose report is more than 30 days old. The response returns `pending_over_30_days` and its rate (`pending_over_30_days_rate`, over reported deaths) as well. It is a count, owned by the field team through the in-charge, and is the blocker view of this KPI.
- **Time Frames:** Snapshot, daily series.
- **Gap:** death to interview time exists only for register cases.

### C-05: % Not Codeable (Overall)

**Question:** How many cases are lost to coding, by whom and why?
- **Classification:** Output / data quality / rate; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj Dt Bk Fu; scope ALL-SYNCED (rate); CODING-POOL for the coder share; peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT where `workflow_state IN ('not_codeable_by_coder', 'not_codeable_by_data_manager')`
- **Denominator:** COUNT of ALL-SYNCED
- **Rate:** N / D × 100
- **Scope:** ALL-SYNCED
- **Time Frames:** Today, 7d, cumulative
- **Drill-down:** By actor (coder vs DM) and by reason

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**D-QG-01: Coder Not-Codeable Count & Rate** (merged as `by=actor_role` (coder))

- Numerator: COUNT where `workflow_state = 'not_codeable_by_coder'`
- Denominator: COUNT of CODING-POOL
- Rate: N/D × 100
- Time Frames: Today, 7d, cumulative

**D-QG-02: DM Not-Codeable Count & Rate** (merged as `by=actor_role` (data manager))

- Numerator: COUNT where `workflow_state = 'not_codeable_by_data_manager'`
- Denominator: COUNT of ALL-SYNCED
- Rate: N/D × 100
- Time Frames: Today, 7d, cumulative

**D-QG-03: Exclusions by Actor** (merged as `by=actor_role`; the reviewer-rejection item is still a known gap (see C-05))

- Definition: COUNT grouped by actor type:
  - DM: `va_data_manager_review` where `va_dmreview_status = 'active'`
  - Coder: `va_coder_review` where `va_creview_status = 'active'`
  - Reviewer rejection: `va_reviewer_review` where `va_rreview = 'rejected'` (quality signal, not workflow state). Not implemented in the code yet (doc drift recorded 2026-10-27, `digitva-0hul`)
  - Screening rejected: workflow events with `transition_id = 'screening_rejected'`
- Time Frames: Cumulative

**D-QG-04: Coder Not-Codeable Reason Breakdown** (merged as `by=reason` (coder))

- Numerator: COUNT grouped by `va_creview_reason`
- Values: `narration_language`, `narration_doesnt_match`, `no_info`, `others`
- Where: `va_creview_status = 'active'`
- Time Frame: Cumulative

**D-QG-05: DM Not-Codeable Reason Breakdown** (merged as `by=reason` (data manager))

- Numerator: COUNT grouped by `va_dmreview_reason`
- Values: `submission_incomplete`, `source_data_mismatch`, `duplicate_submission`, `language_unreadable`, `others`
- Where: `va_dmreview_status = 'active'`
- Time Frame: Cumulative


### C-06: Not Analysable Rate

**Question:** How many interviews cannot be analysed, and why?
- **Classification:** Output / data quality / rate; tier core; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj Dt Bk Fu; scope ALL-SYNCED; peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

Was "Consent Refusal Rate"; renamed 2026-10-01 (`digitva-4tb`). One bucket for
every interview that cannot be analysed, whatever the reason.

- **Numerator:** COUNT where `workflow_state = 'consent_refused'`. That state
  holds every web interview stored as `refused`, `respondent_unavailable` or
  `partially_completed`, and ODK submissions with consent = no.
- **Per-reason subtext:** Refused / Respondent unavailable / Partially
  completed, read from the active payload's `interview_outcome`; a payload
  without one (every ODK submission) counts as Refused. Derived at query time,
  nothing stored: the API serves it as `not_analysable.by_reason`, the
  dashboard card as `not_analysable_by_reason`. The old `consent_refused`
  response key is kept with the same count. The daily grid shows the total
  only (owner, 2026-10-10: keep the grid simple). The per-reason split lives
  on the C-06 card and the dashboard card, not in the grid; stored grid days
  hold no reasons, and splitting them would mean estimates.
- **Denominator:** COUNT of ALL-SYNCED
- **Rate:** N / D × 100
- **Time Frames:** Today, 7d, cumulative

**Outcome** (what the results say: cause quality, equity and cause mix.) Categories: coding quality, equity.

### O-UNK: Unknown Cause Share

**Question:** What share of finals has no meaningful cause?
- **Classification:** Outcome / coding quality / rate; tier core; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt Bk; scope authoritative finals; peers: Rate shown only for n of 20 or more.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of authoritative finals whose WHO 2026 VA cause
  section is "Cause of death unknown" (`UNKNOWN_CAUSE_SECTION`). The measure
  is based on VA causes, per the owner's decision of 2026-10-27. Senility
  (R54) and other ill-defined codes all map there. An ICD breakdown inside
  the section is an optional drill-down.
- **Denominator:** COUNT of authoritative finals.
- **Rate:** N / D × 100. Shown only when D is 20 or more.
- **Meaning:** a final that exists but tells the programme nothing. High values point at coding quality, not at volume.
- **Time Frames:** Snapshot, weekly series.

### D-QG-09: Coder-Reviewer Disagreement Rate

**Question:** Do coders and reviewers agree, at the WHO 2026 bucket level?
- **Classification:** Outcome / coding quality / rate; tier core; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Pj Dt; scope submissions with both an active coder final and an active reviewer final; peers: Rate shown only for n of 20 or more.
- **Direction and threshold:** Lower disagreement is better; no fixed threshold.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- Numerator: COUNT of submissions with an active coder final and an active reviewer final whose **WHO 2026 bucket** differs (owner decision 2026-10-27, `digitva-0hul`). Compared from the COD snapshot MV (`va_submission_cod_snapshot_mv`: `coder_final_who_bucket` vs `reviewer_final_who_bucket`), not `va_conclusive_cod` text; where no bucket exists, the ICD-11 primary stem or ICD-10 code is compared instead. ICD-10 `A/B` post-coordinated codes compare by primary stem.
- Denominator: COUNT of submissions with both coder final assessment AND reviewer final assessment (active)
- Rate: N/D × 100
- Source: `va_submission_cod_snapshot_mv` (refreshed hourly, so the rate can lag a recent finalization)
- Time Frame: Cumulative

### EQ-01: Female Share Against Peers

**Question:** Are female deaths under-reported in some districts, against peers?
- **Classification:** Outcome / equity / gap; tier core; audience DM, admin; cadence monthly.
- **Level, scope and peers:** Dt Bk; scope ALL-SYNCED with sex known; peers: Yes: siblings inside the grant only.
- **Direction and threshold:** Gap to the peer median; a large negative female gap is the signal.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Measure:** the female share of cases with sex known, per district (or per block in a district view), against the median of its siblings inside the viewer's grant.
- **Gap:** unit female share minus peer median, in percentage points. A district that is well below its peers may be under-reporting female deaths.
- **Base:** ALL-SYNCED with sex known. Sex values are raw strings today; they are normalised to female, male and unknown in one place.
- **Suppression:** a unit with fewer than 20 cases shows its count with no share, gap or rank.
- **Not claimed:** this is composition against peers, not a per-population rate. There is no population figure; expected female share (DHS or SRS, `digitva-1835`) and SES, caste and education (`digitva-r9lk`) are later.
- **Time Frames:** Cumulative, monthly series.

### EQ-02: Female-Male Final Cause Gap

**Question:** Do female cases get a final cause as often as male cases?
- **Classification:** Outcome / equity / gap; tier core; audience DM, admin; cadence monthly.
- **Level, scope and peers:** Pj Dt Bk; scope CODING-POOL with sex known; peers: Yes.
- **Direction and threshold:** Gap near 0 is expected.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Measure:** the share of female CODING-POOL cases with an authoritative final cause, minus the same share for male cases.
- **Gap:** female rate minus male rate, in percentage points. Sex is normalised as in EQ-01; unknown sex is left out and reported by EQ-03.
- **Register half (death-register projects only):** the share of reported female deaths that have an interview, minus the male share. It applies to death-register projects only (owner decision 2026-10-27, `digitva-r5s0`); other projects show the final-cause half alone.
- **Suppression:** each sex needs a denominator of 20 or more; otherwise counts only.
- **Time Frames:** Cumulative, monthly series.

---

## Registered KPIs (35)

Queryable, with no fixed panel. Grouped by stage, then category.

**Input** (what the programme has to work with: people and languages.) Categories: workforce.

### D-LC-06: Coder Roster

**Question:** Who are the active coders, with languages and load?
- **Classification:** Input / workforce / roster; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Dt Bk Fu; scope grant scope (`grant_in_scope_sql`); peers: No.
- **Direction and threshold:** Informational.
- **Views:** status.
- **MCP:** none (names people; web only).

**Definition:**

- Definition: Per project, for each active coder: name, email, `vacode_language` list, total forms coded (cumulative), currently allocated count, active since date
- Source: `va_users` JOIN `va_user_access_grants` JOIN `va_final_assessments` COUNT
- Time Frame: Cumulative
- Note: Policy-only definition, not a dashboard widget

### ST-01: Staff per Unit

**Question:** How many staff hold each role in each unit?
- **Classification:** Input / workforce / volume; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Dt Bk Fu; scope active grants in the viewer's subtree; peers: Yes, siblings inside the grant.
- **Direction and threshold:** Informational.
- **Views:** status.
- **MCP:** full (counts only).

**Definition:**

- **Measure:** COUNT of active grant holders by role in each unit of the viewer's subtree (coders, reviewers, data managers, interviewers, supervisors).
- **Output:** counts only. Names stay in D-LC-06 (web only).
- **Why:** the input half of capacity: C-21 says whether coders are busy; ST-01 says how many people there are to do the work.
- **Time Frames:** Snapshot.

**Process** (how cases move: flow, timeliness, coding quality, system health and the correction loop.) Categories: flow, timeliness, coding quality, system, loop.

### C-16: Mean Daily Coding Rate

**Question:** How many cases does the team code per day?
- **Classification:** Process / flow / rate; tier registered; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj Dt; scope CODING-POOL; non-demo finalize events; peers: Yes.
- **Direction and threshold:** Higher is better; read against inflow.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Definition:** Average number of submissions coded per day over the trailing window
- **Formula:** COUNT of non-demo finalize events over the window (live, viewer-timezone days) / COUNT of days in window (owner decision 2026-10-27, `digitva-0hul`)
- **Also report:**
  - Per coder: `SUM of coder_finalized events / days` grouped by `va_finassess_by`
  - Per language: `SUM of coder_finalized events / days` grouped by `va_submissions.va_narration_language`
- **Scope:** CODING-POOL
- **Time Frames:** 7d
- **Actionable:** Tells the DM "your team is averaging N forms/day" — compare against inflow rate to know if you're keeping up

### C-20: Language with Maximum Pendency

**Question:** Which languages have the most pending cases?
- **Classification:** Process / flow / volume; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Dt Bk Fu; scope CODING-POOL; pending set; peers: Yes.
- **Direction and threshold:** Lower is better.
- **Views:** status, forecast.
- **MCP:** full.

**Definition:**

- **Definition:** For each language, COUNT in the 6 pending states (owner decision 2026-10-27, `digitva-0hul`), ordered DESC
- **Display:** Table: Language | Pending | Coders Available | Gap (yes/no) | Predicted Days to Clear
- **Top row = the bottleneck language**
- **Scope:** CODING-POOL (6 pending states)
- **Time Frame:** Snapshot
- **Actionable:** Immediately tells DM which language needs urgent coder recruitment or reallocation

### D-WF-01: CONSORT Pipeline Flowchart

**Question:** How many cases are in each workflow state?
- **Classification:** Process / flow / distribution; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Pj Dt Bk Fu; scope ALL-SYNCED; peers: No.
- **Direction and threshold:** Informational.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Definition: Current count of submissions in each of the 14 workflow states, rendered as a CONSORT-style flowchart with:
  - Main trunk flowing top-to-bottom through pipeline stages
  - Branch points showing terminal states (consent_refused, not_codeable_by_*, finalized_upstream_changed)
  - Flow-through numbers at each stage (total minus cumulative branches)
  - Sub-phases within states (e.g., coder_finalized split by within/beyond the project's recode window) (owner decision 2026-10-27, `digitva-0hul`)
  - Optional states visually distinguished from mandatory trunk states
- Source: `va_submission_workflow` GROUP BY `workflow_state`, scoped by DM sites
- Response includes:
  - `total_synced`: total submissions in DM scope
  - `nodes[]`: each node with `id`, `label`, `count` (in state), `flow_through` (reached this stage), `type` (trunk/optional/terminal/branch), `phase`, `branch_from`
  - `sub_phases` for `coder_finalized`: `within_window` and `beyond_window` counts, with `within_24h` and `beyond_24h` kept for one release (owner decision 2026-10-27, `digitva-0hul`)
  - `conversion`: consent_valid_rate, coding_completion_rate, review_rate
- Rendering: CSS-based flowchart (no chart library). Vertical trunk with horizontal branches. Color-coded by phase.
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/flowchart`
- Time Frame: Snapshot

### D-WF-04: Daily State Transitions

**Question:** How many cases entered each state each day?
- **Classification:** Process / flow / volume; tier registered; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj; scope workflow events; peers: No.
- **Direction and threshold:** Informational.
- **Views:** trend.
- **MCP:** full.

**Definition:**

- Definition: How many submissions entered each state per day over the trailing window
- Extends C-19 (which tracks crossings of the pending boundary) to ALL states
- Source: `va_submission_workflow_events` GROUP BY DATE(event_created_at), current_state
- Response: `days[]` with `date`, `transitions` (dict of state→count), `total`
- Rendering: Stacked bar chart (Chart.js), one bar per day, stacked by target state, color-coded by phase
- Endpoint: `GET /api/v1/analytics/dm-kpi/workflow/daily-transitions?days=7`
- Time Frame: 7d (configurable up to 90d)

### D-WT-02: Upstream Change Resolution Time

**Question:** How long do ODK upstream changes take to resolve?
- **Classification:** Process / timeliness / duration; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Dt; scope `va_submission_upstream_changes`; peers: No.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: For each resolved upstream change in 7d, `resolved_at − created_at`
- Aggregate: PERCENTILE(0.5)
- Source: `va_submission_upstream_changes`
- Note: rows exist for ODK changes only, so send-backs and reopens are already excluded
- Time Frame: 7d

### C-09: % Forms Reviewed

**Question:** What share of coded cases has been reviewed?
- **Classification:** Process / coding quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt; scope CODED; peers: Yes.
- **Direction and threshold:** Higher is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of submissions that have at least one `va_reviewer_final_assessments` row with active status
- **Denominator:** COUNT of submissions that ever reached `coder_finalized` (i.e., CODED scope, excluding those still in coder-finalized if reviewer window hasn't passed)
- **Refined denominator:** COUNT where `workflow_state IN ('reviewer_eligible', 'reviewer_coding_in_progress', 'reviewer_finalized')` OR has a reviewer_finalized event in history
- **Rate:** N / D × 100
- **Scope:** CODED
- **Time Frames:** 7d, cumulative
- **Note:** The project's recode window (`recode_window_minutes`, not a fixed 24 h) means reviewer-eligible forms can't be reviewed immediately. Denominator excludes `coder_finalized` forms younger than that window (owner decision 2026-10-27, `digitva-0hul`).

### D-WT-04: Reopen Rate

**Question:** How often are finalized cases reopened for recoding?
- **Classification:** Process / coding quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt; scope CODED; peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT of events with `transition_id IN ('upstream_change_accepted', 'admin_override_to_recode')` in window, minus events whose `transition_reason` is `interviewer_revision` (the interviewer's revision restarting a sent-back case) or `interview_chosen` (a supervisor's choice of the other interview); neither is a data-manager reopen
- Companion: `d_wt_04_revision_restarts_7d` counts the `interviewer_revision` restarts
- Denominator: COUNT of `coder_finalized` events in window
- Rate: N/D × 100
- Scope: CODED
- Meaning: What fraction of finalized forms were re-opened for recoding
- Time Frames: 7d, cumulative

### CQ-FAST: Share of Fast Finals

**Question:** What share of finals was finished suspiciously fast?
- **Classification:** Process / coding quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt; scope non-demo finalize events; peers: Rate shown only for n of 20 or more.
- **Direction and threshold:** Lower is better. Cut-off: 180 seconds
  (3 minutes) by default, held as a registry value so it can be adjusted.
- **Views:** status.
- **MCP:** full (totals; per-coder rows web only).

**Definition:**

- **Numerator:** COUNT of non-demo finalize events whose time to code (see canonical terms) is under the registry cut-off.
- **Denominator:** COUNT of non-demo finalize events in the window.
- **Rate:** N / D × 100. Shown only when D is 20 or more.
- **By coder:** per-coder rows name people, so they are web only, for DMs in scope; MCP returns totals.
- **Cut-off:** 180 seconds by default. This is elapsed time between
  workflow events, not time on screen.
- **Time Frames:** 7d, cumulative.

### C-13: Sync Latency (ODK → App)

**Question:** How long does a submission take to reach DigitVA from ODK?
- **Classification:** Process / system / duration; tier registered; audience DM, admin; cadence daily.
- **Level, scope and peers:** Sys Pj; scope ODK-sourced ALL-SYNCED; peers: No.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- **Definition:** For submissions synced in window: time between ODK submission timestamp and local DB insert
- **Formula:** `va_created_at − va_submission_date` per submission, ODK-sourced forms only (`form_source = 'odk'`) (owner decision 2026-10-27, `digitva-0hul`)
- **Aggregates:** P50, P90, P99
- **Time Frames:** Today, 7d

### C-14: Attachment Health

**Question:** How many ODK submissions are missing their attachments?
- **Classification:** Process / system / rate; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Pj Dt Fu; scope ODK-sourced submissions past the SmartVA gate; peers: Yes.
- **Direction and threshold:** Lower is better; 0 expected.
- **Views:** status.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of ODK-sourced submissions past SmartVA gate where attachment count = 0 (owner decision 2026-10-27, `digitva-0hul`)
- **Denominator:** COUNT of ODK-sourced submissions past SmartVA gate
- **Rate:** N / D × 100
- **Source:** `va_submission_attachments` JOIN `va_submissions`
- **Time Frame:** Snapshot

### D-SH-01: Attachment Download Completeness

**Question:** Did the last sync download its attachments?
- **Classification:** Process / system / rate; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Sys; scope latest `va_sync_runs` row; peers: No.
- **Direction and threshold:** Higher is better; 100% expected.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: `va_sync_runs.attachment_downloaded` from latest run
- Denominator: the same run's `attachment_forms_total` (owner decision 2026-10-27, `digitva-0hul`) (the code's denominator; the earlier text said downloaded + skipped + errors)
- Rate: N/D × 100
- Time Frame: Snapshot

### D-SH-04: SmartVA Failure Rate

**Question:** How often does SmartVA fail?
- **Classification:** Process / system / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Sys; scope `va_smartva_runs`; peers: No.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT of `va_smartva_runs` where `va_smartva_outcome = 'failed'` in window
- Denominator: COUNT of all `va_smartva_runs` in window
- Rate: N/D × 100
- Time Frames: 7d, cumulative

### D-SH-02: ODK Coverage Delta

**Question:** Does ODK Central hold more submissions than DigitVA?
- **Classification:** Process / system / gap; tier registered; audience DM, admin; cadence on demand.
- **Level, scope and peers:** Pj-St; scope live ODK call; peers: No.
- **Direction and threshold:** 0 expected.
- **Views:** status.
- **MCP:** none (web only; live ODK call).

**Definition:**

- Definition: Per form, ODK-side submission count (from preview) minus local COUNT
- Source: Sync preview logic (live ODK call)
- Time Frame: On-demand

### CL-01: Send-back and Reopen Rate by Reason

**Question:** How often are cases sent back or reopened, and why?
- **Classification:** Process / loop / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt Bk Fu; scope Collect-sourced cases (`va_forms.form_source`); peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status, trend.
- **MCP:** full (`by=actor_role`).

**Definition:**

- **Collect only.** Send-back and reopen exist only for Collect-sourced cases; ODK submissions are refused, and ODK uses `hasIssues` plus Central edits instead. The split is `va_forms.form_source`. Browser against device is not split.
- **Numerator:** COUNT of send-back and reopen workflow events (`sent_back_for_revision`, `reopened_for_revision`) in the window.
- **Denominator:** COUNT of finalize events in the window.
- **Reason:** read from the submission audit row (`<reason>:<code>`), paired with the workflow event by `LATERAL`. `by=actor_role` is available.
- **ODK proxy:** hasIssues plus upstream-change counts, shown as a proxy only. ODK review-state history is not stored, so ODK reasons, time to correct and repeat flags are not captured.
- **Per-interviewer rows name people:** web only, for DMs and ICs in scope, and never sent over MCP.
- **Time Frames:** 7d, cumulative.

### CL-02: Time to Correct

**Question:** How long does a correction take, send-back to revision?
- **Classification:** Process / loop / duration; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt Bk Fu; scope Collect-sourced cases; peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status, trend, critical path.
- **MCP:** full (totals).

**Definition:**

- **Collect only.** See CL-01.
- **Measure:** each correction request paired with the next `interviewer_revision` event. Median and p90 of the gap, in hours.
- **Open and cancelled requests:** counted, with no duration.
- **Critical path:** it is the "correction" stage of the D-WF-02 critical path.
- **ODK:** not captured, because ODK review-state history is not stored.
- **Time Frames:** 7d, cumulative.

### CL-04: Supervisor Review Turnaround

**Question:** How long does supervisor review take?
- **Classification:** Process / loop / duration; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt; scope projects with the supervisor review switch on; peers: Rate shown only for n of 20 or more.
- **Direction and threshold:** Lower is better. Inactive until `digitva-ydnl.4` ships.
- **Views:** status, trend.
- **MCP:** full once active.

**Definition:**

- **Inactive until `digitva-ydnl.4` ships.**
- **Measure:** time from a case being submitted for supervisor review to the supervisor's decision. Median and p90 in hours.
- **Scope:** only projects that have the supervisor review switch on.
- **Time Frames:** 7d, cumulative.

**Output** (what the process produces: coded cases, coverage, data quality and workforce output.) Categories: flow, coverage, data quality, workforce, loop.

### C-18: Predicted vs Achieved (Burndown)

**Question:** Are we ahead of or behind the target-date trajectory?
- **Classification:** Output / flow / net; tier registered; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj; scope CODING-POOL; peers: No.
- **Direction and threshold:** Achieved line above projected line means behind schedule.
- **Views:** trend, forecast (it is the forecast of AD-FCOD).
- **MCP:** full.

**Definition:**

- **Definition:** Chart comparing projected completion trajectory vs actual cumulative coding progress
- **Projected line:** At project start (or target date set), draw a straight line from (start, total_forms) to (target_date, 0). Daily point: `total − (days_elapsed × daily_target_rate)`
- **Achieved line:** Cumulative CODED submissions over time, rebuilt live from workflow events, not from `va_daily_kpi_aggregates` (owner decision 2026-10-27, `digitva-0hul`)
- **Requires:** `project_target_completion_date` set by admin
- **Display:** Line chart, two lines, X-axis = time, Y-axis = remaining forms
- **Actionable:** If achieved line is above projected line, the project is behind schedule. The gap tells the DM exactly how far behind.
- **Time Frame:** Daily series from project start to target date

### D-QG-08: Social Autopsy Completion Rate

**Question:** What share of coded cases has a social autopsy?
- **Classification:** Output / coverage / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj; scope CODED in projects with `social_autopsy_enabled`; peers: No.
- **Direction and threshold:** Higher is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT of submissions with at least one active `va_social_autopsy_analyses` row (where `va_saa_status = 'active'`)
- Denominator: COUNT of CODED submissions WHERE the submission's own project has `social_autopsy_enabled = true` (joined on the form's project) (owner decision 2026-10-27, `digitva-0hul`)
- Rate: N/D × 100
- Inclusions: Only projects where `social_autopsy_enabled = true`
- Exclusions: Projects where `social_autopsy_enabled = false`
- Time Frame: Cumulative

### D-LC-01: Submission Language Distribution

**Question:** What languages are the interviews in?
- **Classification:** Output / coverage / distribution; tier registered; audience DM, admin; cadence monthly.
- **Level, scope and peers:** Pj; scope CONSENT-VALID; peers: No.
- **Direction and threshold:** Informational.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- Numerator: COUNT grouped by `lower(trim(va_narration_language))` (owner decision 2026-10-27, `digitva-0hul`) ("English" and "english" are one group)
- Denominator scope: CONSENT-VALID
- Where: `va_narration_language IS NOT NULL`
- Time Frame: Cumulative
- Also report: Trend over time (monthly)

### AD-VN: Visit Notes

**Question:** Where are interviews not completed (refused or respondent
unavailable), and is each visit documented?
- **Classification:** Output / coverage / volume; tier registered;
  audience IC, DM; cadence weekly.
- **Level, scope and peers:** Dt Bk Fu; scope supervised Collect cases
  in the viewer's scope; peers: Yes, counts only.
- **Direction and threshold:** Informational; no fixed threshold.
- **Views:** status.
- **MCP:** totals only (no address or remarks).

**Definition:**

- **Count:** supervised cases whose active payload holds a visit note
  (`visit_date`, `visit_address`, `visit_remarks`, recorded with a refused
  or unavailable interview outcome). This is the same predicate as the
  supervision and submissions `visit_note=1` filter, by unit.
- **Privacy:** address and remarks are never part of the KPI. Viewers that
  `should_redact_pii` sees only the date, and MCP returns counts only.
- **Applies to** DigitVA Collect and web intake. ODK has no visit note.
- **Time Frames:** Snapshot, weekly.

### D-QG-06: ODK Has Issues Count

**Question:** How many cases does ODK flag with issues?
- **Classification:** Output / data quality / rate; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Pj Dt; scope ALL-SYNCED; peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT where `va_odk_reviewstate = 'hasIssues'`
- Denominator: ALL-SYNCED
- Time Frame: Cumulative

### D-LC-07: Forms with Missing/Unmapped Language

**Question:** How many cases have no usable language?
- **Classification:** Output / data quality / rate; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Dt; scope CODING-POOL; peers: Yes.
- **Direction and threshold:** Lower is better; 0 expected.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT where `va_narration_language IS NULL OR va_narration_language = '' OR va_narration_language NOT IN (SELECT alias FROM map_language_aliases)`
- Denominator: COUNT of CODING-POOL
- Rate: N/D × 100
- Scope: CODING-POOL
- Time Frame: Snapshot
- Actionable: These forms cannot be language-matched to coders. Either the ODK form doesn't collect language, the value isn't in the alias mapping table, or the field is blank. DM action: check alias mapping, update ODK form, or manually assign language

### C-11: % Forms with Upstream Changes

**Question:** How many coded cases had ODK data change after finalization?
- **Classification:** Output / data quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Dt Bk Fu; scope CODED; peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of submissions that have at least one `va_submission_workflow_events` row with `transition_id = 'upstream_change_detected'` whose `transition_reason` is not a revision request (`sent_back_for_revision`, `reopened_for_revision`) or `interview_chosen`: ODK changes only
- **Denominator:** COUNT of CODED submissions
- **Rate:** N / D × 100
- **Scope:** CODED
- **Time Frames:** 7d, cumulative
- **Meaning:** What fraction of coded forms had ODK data change after finalization

### D-SH-03: Locally Missing in ODK

**Question:** How many local cases no longer exist in ODK?
- **Classification:** Output / data quality / rate; tier registered; audience DM, admin; cadence snapshot.
- **Level, scope and peers:** Pj; scope ALL-SYNCED plus the retired rows; peers: No.
- **Direction and threshold:** Lower is better; 0 expected.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT where `va_sync_issue_code = 'missing_in_odk'` (the core
  analytics MV's `odk_missing` column)
- Denominator: ALL-SYNCED *plus* the retired rows themselves — this KPI is the
  one place that counts them, and it ignores the default exclusion
- Surfaced as the "Missing in ODK" card on the data-manager dashboard
  (`missing_in_odk_submissions`); clicking it filters the list to
  `odk_sync=missing_in_odk`
- Time Frame: Cumulative

### D-QG-07: NQA Completion Rate

**Question:** What share of coded cases has a narrative quality assessment?
- **Classification:** Output / data quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj; scope CODED in projects with `narrative_qa_enabled`; peers: No.
- **Direction and threshold:** Higher is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT of submissions with at least one active `va_narrative_assessments` row (where `va_nqa_status = 'active'`)
- Denominator: COUNT of CODED submissions WHERE the submission's own project has `narrative_qa_enabled = true` (joined on the form's project, never a project at the same site) (owner decision 2026-10-27, `digitva-0hul`)
- Rate: N/D × 100
- Inclusions: Only projects where `narrative_qa_enabled = true`
- Exclusions: Projects where `narrative_qa_enabled = false` (excluded from both N and D)
- Time Frame: Cumulative

### D-LC-05: Language-Not-Codeable Correlation

**Question:** Do language not-codeable decisions match the coder gap?
- **Classification:** Output / data quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt; scope language not-codeable reviews; peers: No.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full.

**Definition:**

- Numerator: COUNT of `va_coder_review` where `va_creview_reason = 'narration_language'` AND submission's `va_narration_language` is in the gap set (D-LC-03)
- Denominator: COUNT of all `va_coder_review` where `va_creview_reason = 'narration_language'`
- Rate: N/D × 100
- Time Frame: Cumulative

### EQ-03: Sex or Age Unknown

**Question:** How many cases have sex or age unknown?
- **Classification:** Output / data quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt Bk; scope ALL-SYNCED; peers: Yes.
- **Direction and threshold:** Lower is better; it guards the validity of EQ-01 and EQ-02.
- **Views:** status.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of ALL-SYNCED submissions where sex or age is missing or unrecognised.
- **Denominator:** COUNT of ALL-SYNCED.
- **Rate:** N / D × 100.
- **Meaning:** guards the validity of EQ-01 and EQ-02; if it is high, their gaps are not trustworthy.
- **Time Frames:** Snapshot, weekly series.

### C-12: Coder Throughput

**Question:** How many cases does each coder finish?
- **Classification:** Output / workforce / volume; tier registered; audience DM, admin; cadence daily.
- **Level, scope and peers:** Dt; scope non-demo finalize events; peers: Yes.
- **Direction and threshold:** Informational.
- **Views:** status.
- **MCP:** totals_only.

**Definition:**

- **Numerator:** COUNT of workflow events with `transition_id IN ('coder_finalized', 'recode_finalized')` in window
- **Denominator:** — (raw count)
- **Also report:** Per-coder breakdown
- **Scope:** CODING-POOL
- **Time Frames:** Today, yesterday, 7d, cumulative
- **Inclusions:** Non-demo events only (owner decision 2026-10-27, `digitva-0hul`)

### C-24: Forms per Coder by Language

**Question:** Which coder codes which language?
- **Classification:** Output / workforce / matrix; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Dt; scope CODED; peers: No.
- **Direction and threshold:** Informational.
- **Views:** status.
- **MCP:** none (names people; web only).

**Definition:**

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

#### Merged definitions

These KPIs were merged into this one (owner decision 2026-10-27, `digitva-r5s0`). Their definitions are kept here unchanged and still apply to the matching `by=` or `view=`.

**D-LC-04: Coder Output by Language** (merged as `by=coder,language`)

- Numerator: COUNT of `va_final_assessments` (active) grouped by (`va_finassess_by`, `va_submissions.va_narration_language`)
- Denominator scope: CODED
- Time Frames: 7d, cumulative
- Sliceable by: coder, language, project, site


### D-WT-01: Reviewer Throughput

**Question:** How many cases do reviewers finish?
- **Classification:** Output / workforce / volume; tier registered; audience DM, admin; cadence daily.
- **Level, scope and peers:** Pj Dt; scope `reviewer_finalized` events; peers: Yes.
- **Direction and threshold:** Informational.
- **Views:** status.
- **MCP:** totals_only.

**Definition:**

- Numerator: COUNT of events with `transition_id = 'reviewer_finalized'` in window
- Time Frames: Today, 7d, cumulative

### CL-03: Repeat Send-backs

**Question:** How many cases were sent back twice or more?
- **Classification:** Output / loop / volume; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt Bk Fu; scope Collect-sourced cases; peers: Yes.
- **Direction and threshold:** Lower is better; no fixed threshold.
- **Views:** status.
- **MCP:** full (totals).

**Definition:**

- **Collect only.** See CL-01.
- **Numerator:** COUNT of cases with 2 or more correction requests.
- **Denominator:** COUNT of cases with at least 1 correction request.
- **Meaning:** a case that comes back twice points at an unclear instruction or a field-team gap.
- **Per-interviewer rows name people:** web only, never over MCP.
- **Time Frames:** Cumulative.

**Outcome** (what the results say: cause quality, equity and cause mix.) Categories: coding quality, cause mix.

### SV-AGR: Agreement with SmartVA

**Question:** How often does the final cause agree with SmartVA?
- **Classification:** Outcome / coding quality / rate; tier registered; audience DM, admin; cadence weekly.
- **Level, scope and peers:** Pj Dt; scope authoritative finals with a SmartVA result; peers: Rate shown only for n of 20 or more.
- **Direction and threshold:** Informational; read with D-QG-09.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Numerator:** COUNT of authoritative finals whose WHO 2026 bucket equals the bucket of the case's SmartVA result.
- **Denominator:** COUNT of authoritative finals that have a SmartVA result mapped to a bucket.
- **Rate:** N / D × 100. Shown only when D is 20 or more.
- **Meaning:** how often the human final and the automated result agree. It is a quality signal, not a target to maximise: SmartVA is an input to coding, not the truth.
- **Time Frames:** Cumulative, weekly series.

### MO-01: Cause Mix

**Question:** What is the cause mix?
- **Classification:** Outcome / cause mix / distribution; tier registered; audience DM, admin; cadence monthly.
- **Level, scope and peers:** Pj Dt; scope authoritative finals; peers: Yes.
- **Direction and threshold:** Informational.
- **Views:** status, trend.
- **MCP:** full.

**Definition:**

- **Measure:** COUNT of authoritative finals by WHO 2026 bucket, with the share of each (the cause mix).
- **Base:** authoritative finals. Counts under 5 are folded; shares are shown only when the base is 20 or more.
- **Meaning:** what the programme is finding. It is context for the quality KPIs, not a performance measure.
- **Answerable from the AI cube** (`kpi_MO-01` catalog entry).
- **Time Frames:** Cumulative, monthly series.

**Correction-loop facts** (owner decision 2026-10-27, `digitva-r5s0`):

- **Send-back and reopen are Collect only.** ODK submissions are refused, and ODK uses `hasIssues` plus Central edits instead.
- **ODK review-state history is not stored,** so ODK time to correct, repeat flags and reasons are not captured.
- **Per-interviewer rows name people,** so they are web only, for DMs and ICs in scope, and never sent over MCP.
- **The Collect/ODK split** is `va_forms.form_source`. Browser against device is not split.
- See also [Interview Revisions Policy](interview-revisions.md).


---

## Merged KPIs (16)

Each id still resolves. The definition sits under the surviving KPI, in its "Merged definitions" block.

### C-02: Last Sync Run Status

Merged into C-03 (as `view=status` (last run row)). Definition kept under C-03.

### C-10: Upstream Change Queue

Merged into C-23 (as the "Upstream change pending" row, `by=reason`). Definition kept under C-23.

### C-17: Predicted Days to Clear Backlog

Merged into C-04 (as `view=forecast`). Definition kept under C-04.

### C-22: Site-Level Bottleneck

Merged into C-04 (as `by=unit` (peer view)). Definition kept under C-04.

### D-LC-02: Coder Language Pool

Merged into C-21 (as `by=language` (counts; names stay in D-LC-06)). Definition kept under C-21.

### D-LC-03: Language Gap Analysis

Merged into C-15 (as `by=language`). Definition kept under C-15.

### D-LC-04: Coder Output by Language

Merged into C-24 (as `by=coder,language`). Definition kept under C-24.

### D-PS-01: Project-wise Form Counts

Merged into C-01 (as `by=project`). Definition kept under C-01.

### D-PS-02: Site-wise within Project

Merged into C-01 (as `by=site`). Definition kept under C-01.

### D-QG-01: Coder Not-Codeable Count & Rate

Merged into C-05 (as `by=actor_role` (coder)). Definition kept under C-05.

### D-QG-02: DM Not-Codeable Count & Rate

Merged into C-05 (as `by=actor_role` (data manager)). Definition kept under C-05.

### D-QG-03: Exclusions by Actor

Merged into C-05 (as `by=actor_role`; the reviewer-rejection item is still a known gap (see C-05)). Definition kept under C-05.

### D-QG-04: Coder Not-Codeable Reason Breakdown

Merged into C-05 (as `by=reason` (coder)). Definition kept under C-05.

### D-QG-05: DM Not-Codeable Reason Breakdown

Merged into C-05 (as `by=reason` (data manager)). Definition kept under C-05.

### D-WF-03: State Stagnation Alerts

Merged into C-07 (as `by=state`; the threshold table is kept unchanged under C-07). Definition kept under C-07.

### D-WT-03: Coding Backlog Trend

Merged into C-04 (as `view=trend`). Definition kept under C-04.

---

## Retired

### D-PS-03: Project Feature Summary

Retired: a configuration listing (feature flags and coder counts per project), not a measure of performance. It lives in Project Setup and the people pages.

**Stored aggregates (no ids).** Retired by owner decision 2026-10-27, `digitva-0hul` (see "Aggregates are retired as a read source"). Not measures; they were a storage layer:

- stored total, new and updated counts: site-keyed, mixed web and ODK, never recounted after retirement;
- stored event counts (coded, reviewer, reopened, consent, not-codeable): no demo exclusion;
- stored end-of-day state (pending, upstream changed): stamped the current state on past dates;
- stored coding durations: the fan-out join of the old C-08.


---

## Analytic views

(owner decision 2026-10-27, `digitva-r5s0`.) A KPI's `views` field says which of these four views it supports. The rules are the same for every KPI.

### Blocker view (C-23)

- A **count**, an **age** (p50 and max) and an **owner** for each blocker reason, by unit, against peers.
- Owners are listed under C-23.
- Non-blocker states (screening and upstream rows) keep current values only; there is no history for them.

### Critical-path view (D-WF-02)

- The **median and p90 time in each stage**, from workflow events, over the last `days` viewer days (1 to 90, default 30).
- **Stages** are `PENDING_STATES` plus `finalized_upstream_changed`, split into the `sent_back_for_revision` correction stage (the Collect correction, CL-02) by the reason of the event that entered it.
- The **dominant stage** is the one with the largest median share of end-to-end time, among stages with n of 20 or more.
- The **bottleneck** is the stage with the largest positive gap to the sibling median, among stages with n of 20 or more.
- The **end segments** (death to interview, interview to final cause) come from `_medians`, all time, and refresh with the core MV. They are not limited to `days`.
- Endpoint: `GET /api/v1/analytics/dm-kpi/critical-path/?days=`.

### Forecast view

- `days_to_clear = pending ÷ 28-day moving average of outflow`.
- **Range:** from the lowest and highest of the last four weekly rates.
- **Capacity assumption:** a ceiling (coders × their recent rate) is shown as an assumption, not mixed into the estimate.
- **"Does not clear"** is flagged when the 28-day net inflow is above 0.
- **Backtest:** weekly over the last 12 weeks, comparing each forecast with the actual pending 14 days later. It reports the share inside the range and the mean absolute error.
- **Suppression:** under 20 cases, no forecast is shown.

### Trend view

- A series with the **change from the previous period**, and the **same period last year** when 13 months of history exist.
- **Flag:** `rising` or `falling` when the mean of the last 4 weeks differs from the mean of the prior 4 weeks by at least 10% **and** at least 5 cases; otherwise `flat`.
- **No flag** under n of 20.

### Known gaps

- web-intake interview start and end times;
- death to interview time, which exists only for register cases;
- imported cases that have no events;
- non-state blocker rows, which keep current values only;
- C-21 history, not yet verified;
- unit routing history and recode-window history;
- no population figure, and no time on screen.


## KPI registry and MCP access

(owner decision 2026-10-27, `digitva-r5s0`.)

### Registry

- **`app/data/kpi_registry.json`** is the machine-readable source. It uses only the stdlib and is loaded like the AI question catalog.
- **Fields:**
  - `id`, `name`, `question`;
  - `stage`, `category`, `type`;
  - `level[]`, `audience[]`, `cadence`;
  - `tier`, `merged_into`, `retired_reason`;
  - `views[]`;
  - `definition` (measure, base, canonical terms) and `helper`;
  - `unit`, `direction`, `thresholds`;
  - `peer`, `min_whole`, `cell_min`;
  - `periods[]`, `dimensions[]`;
  - `sources[]`, `replaces[]`;
  - `mcp` (full, totals_only or none) and `catalog_key`;
  - `policy_anchor` and `decisions[]`.
- **Drift test (no generator):** every non-retired id has its `### <id>:` heading in this document and every heading has a registry entry; every non-null `helper` imports (a
  core or registered KPI whose function is not written yet carries
  `helper: null` and `helper_status: "pending"`, and nothing else may be
  null); every `catalog_key` and every `merged_into` target exists. Retired ids are the exception: they keep a heading and a `retired_reason`.
- **The help page renders from the registry:** its KPI table is read from the JSON, so the help text and this document cannot drift apart.
- **Search:** a `kpi` kind in `ai_search_service`. Results link to `/help/kpis#<id>` and are restricted to DMs and admins.
- **AI question catalog:** cube-answerable KPIs (O-UNK, EQ-01 to EQ-03, AD-FCOD, C-05, C-06, MO-01, D-LC-01) get `kpi_<id>` catalog entries. Event-based KPIs point to the dashboard or MCP, and the model's "not captured" list names them. See [AI Analytics Questions](ai-analytics-questions.md).

### MCP access

A minimal Model Context Protocol endpoint serves the registry to AI agents: `POST /api/v1/mcp`, plain JSON-RPC over Streamable HTTP (`initialize`, `tools/list`, `tools/call`), hand written, no SDK and no SSE. The access rules are in [Access Control Model](access-control-model.md#mcp-access-for-kpi-reads-owner-2026-10-27-digitva-r5s0).

- **Tools:**
  - `list_kpis(stage, category, level, audience, tier, q)`;
  - `describe_kpi(id)`, which includes the caller's scope summary;
  - `get_kpi_values(kpi_id, scope, period, compare, by, view)`. `scope` can only narrow the caller's own scope; anything outside it is a 403.
- **Aggregates only:** counts under 5 become `<5`, a rate with a denominator under 20 is left out (null), and no names are returned. A registry entry marked `mcp: totals_only` or `none` returns no per-person rows.
- **Suppression:** cell-level only for now. Complementary suppression is needed if MCP output is ever published further.


## Daily Operations Grid (DM's Primary View)

The daily grid (C-01) is the landing view:

| Date | Total | New from ODK | Updated in ODK | Coded | Pending | Not analysable | Not Codeable |
|------|-------|-------------|----------------|-------|---------|-----------------|--------------|
| Today | 1,281 | +8 | +2 | 5 | 115 | 2 | 1 |
| Yesterday | 1,273 | +12 | +1 | 9 | 108 | 1 | 3 |
| ... | ... | ... | ... | ... | ... | ... | ... |
| 7 days ago | 1,190 | +10 | +3 | 7 | 82 | 1 | 1 |

Below the grid sit the **core panels** (owner decision 2026-10-27, `digitva-r5s0`): coder availability, language gap, uncoded and forecast, inflow against outflow, blockers, aging, time to code, the critical path, ODK sync, coverage and final cause, not-codeable and not-analysable, cause quality, coder-reviewer agreement and equity. Registered KPIs are reached by id from the registry, the search box or MCP.

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
| `GET /api/v1/data-management/kpi` | KPI card counts (core panels) | Async, cached 5 min |
| `GET /api/v1/data-management/daily-grid` | Daily operations grid rows | Async, computed live from workflow events |
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
3. **Medium (<2s):** Daily grid, charts load (computed live)
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
3. **`va_daily_kpi_aggregates` table** — retired as a read source (see "Aggregates are retired as a read source")
4. **Not-codeable reason in MV** — for D-QG-04, D-QG-05 breakdowns without review-table joins
5. **Coding duration pre-computation** — only if live time-to-code misses its budget

---

## Files

### Create
- `docs/policy/kpis.md`
- `app/data/kpi_registry.json` (step 5 of `digitva-r5s0`)

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
- [ ] KPI storage model defined (live from workflow events; aggregates retired as a read source)
- [ ] Hard gates with 4 denominator scopes and inclusion/exclusion rules
- [ ] Time frames on every KPI
- [ ] Core panels (18) + Registered KPIs (35), with merged and retired ids resolving
- [ ] Every KPI has exact numerator/denominator with inclusion/exclusion rules
- [ ] Daily operations grid with 7 columns defined
- [ ] Time to Code with min/max/median/P90
- [ ] % Forms Reviewed with project recode window exclusion
- [ ] % Uncoded, % Not Codeable, % Upstream Changes
- [ ] Reopen Rate (D-WT-04) registered
- [ ] Not-codeable reasons match form choices
- [ ] Reviewer rejection described as quality signal
- [ ] NQA/SA linked to project flags with exclusion rules
- [ ] MV enhancement appendix included
- [ ] Cross-references existing policy docs

