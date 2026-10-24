# Expo dashboards: Statistics, Data, Users access, Mentor view

Beads: digitva-jv14 (Statistics, in fix-up), digitva-3f72 (Data), digitva-3vj8 + digitva-oux5 (Mentor). Owner ask 2026-10-24: Expo views for data managers and mentor institutions plus the district statistics dashboard; match the existing Expo theme; key statistics and row-level data per audience. Inventory from a read-only audit of the Flask pages, 2026-10-24.

## Platform

All of these are web-only, cookie session: `role_required` refuses bearer tokens unless a native role is listed, and `/api/v1/area/*` and `/api/v1/users*` are `browser_session_only`. Downloads may 302 to a presigned S3 URL: navigate or use an anchor, never `fetch`. Background polls send `X-DigitVA-Background`.

## The four Flask dashboards and their Expo home

| Flask | Expo | Gate (server is the authority) |
| --- | --- | --- |
| `/area/` | `/statistics` | any active grant |
| `/data-management/` | `/data` Overview | data_manager, collaborator, collaborator_pii (plain collaborator redacted) |
| `/data-management/dashboard` | `/data` Pipeline | data_manager, admin |
| `/data-management/cod-buckets` | `/data` Causes | data_manager, admin |
| `/data-management/users` | `/users` Access view (new) | data_manager (incl. In-charge, tree project_pi), admin |

`data_manager` here is `effective_roles`: a DM grant at any scope, the In-charge (site_pi at a unit), or project_pi on a tree project.

## Statistics (`/statistics`, `/api/v1/area/*`)

Query params `project` (required), `unit`, `site`, `period` (`30d|90d|12m|all`); unit+site together is 404. Counts per card and row: deaths_reported, deaths_7_days, deaths_30_days, interviews_pending, pending_over_7_days, pending_over_30_days, submitted, awaiting_coding, not_codeable, final_cod, smartva_failed, visit_notes. Medians are all time. Causes: hidden under 20 coded, top 10 with n>=5, the rest (small causes, past the top ten, unmapped codes) in "Other". Staff view: interviewers only, names only when not redacted, cap 500. Card and row links are Flask paths: once `/data` exists, map `data_management.dashboard` links to `/data` with the same query.

## Data Overview (`/api/v1/data-management/*`)

Cards (11, from `/kpi`, filtered; a click sets a filter): Total; Pending coding `workflow=pending_coding`; SmartVA queue `workflow=smartva_pending`; Coded `workflow=coded`; Upstream changed `workflow=finalized_upstream_changed`; Needs field attention `odk_status=hasIssues`; Not codeable (DM) `workflow=not_codeable_by_data_manager`; Not analysable `workflow=consent_refused` with the refused/unavailable/partial split; Missing in ODK `odk_sync=missing_in_odk`; SmartVA missing `smartva=missing`; SmartVA failed `smartva=failed`. Cards come from a 300 s view and can lag the live list: show freshness and a Refresh (POST `/analytics/mv/refresh`, 5/min). Known card/list mismatches: digitva-l945.

Filters. The URL is authoritative; never overlay saved state on a shared link. `search`; `project` and `site` (comma lists); `date_from`, `date_to`; `odk_status` (`hasIssues|approved|no_review_state`); `smartva` (`available|missing|failed`); `age_group` (`neonate|child|15_49y|50_64y|65_plus|unknown`); `gender` (from `/filter-options`, which now lists distinct lower-cased values; the filter compares lower-cased; the picker capitalises); `odk_sync` (`in_sync` default, `missing_in_odk`, `all`); `workflow` (groups `pending_coding`, `coded`, plus the 15 states); `visit_note=1`; `org_unit`; paging `page`, `size` (10-100); sort `sort_field`, `sort_dir`, sent to the API as `sort[0][field]` / `sort[0][dir]`, allowed fields va_uniqueid_masked, project_id, site_id, workflow_state, va_dmreview_createdat, va_submission_date, coded_on, coded_by; `selected_sid`. Default `odk_sync=in_sync&sort_field=va_submission_date&sort_dir=desc`.

Rows (phone: one card per row; wide: table): Site, Submitted, VA form ID (masked), Attachments, SmartVA (Ineligible/Available/Missing/Failed; Failed needs digitva-i347), ODK status (with review comments), Workflow state (sent back for revision in its own colour), Coded on, Coded by; optional Project, Data collector, Age group, Gender, ODK sync, Flagged at, Consent, Visit note. Redacted viewer: data collector and coded by blank, search on masked ID only, visit-note address withheld, no coded_by sort (digitva-10fd).

Row actions: View (data_manager/admin: Flask `/data-management/view/<sid>`, which holds the triage panel and Not codeable; viewers: `/coding/area/<sid>`); Edit in ODK (new tab); for upstream changes "View changes" with Accept and recode / Keep current decision (each confirmed); for revision requests "Cancel request". In v1 these stay Flask links, except View changes, which is JSON and fits a dialog.

Charts and side panels (data_manager only): submissions by site (`/project-site-submissions`; `group_by=org_unit` for tree projects), age and sex (`/analytics/demographics`), workflow distribution (from `workflow_counts`, click filters), coder daily stats for 7 days (`/coder-daily-stats`, click sets search).

Exports (data_manager only; they honour the filters but not `visit_note`, `org_unit` or sort, so say so): submissions CSV (staff user ids), coded COD snapshot (staff names), SmartVA input, results, likelihoods. Sync (data_manager with a project or site grant): runs, preview, queue; v1 links to the Flask Operations panel.

## Data Pipeline (`/api/v1/analytics/dm-kpi/*`)

No project filter (scope combined); window 7/30/90. Headline: pending backlog (C-17), daily coding rate (C-16), days to clear (C-17), coder utilisation (C-21). Sections: daily grid 8 days (C-01); workflow flowchart and conversion (D-WF-01), stagnation (D-WF-03), state velocity 30 d (D-WF-02), daily transitions (D-WF-04); sync status, error rate, latency (C-02, C-03, C-13), attachment health (C-14); quality: not codeable (C-05), not analysable (C-06), reviewed (C-09), upstream queue (C-10, C-11), blocked breakdown (C-23); burndown (C-18), inflow vs outflow (C-19), aging and time to code (C-07, C-08; time to code is always 7 d today), site bottleneck (C-22), backlog trend (D-WT-03), language gap (C-15, C-20), coder output 7 d or cumulative (C-12, C-16, C-24). Refresh POST `/dm-kpi/refresh` (2/min).

## Data Causes (`/api/v1/cod-buckets/*`)

data_manager and admin only. Scheme picker (default scheme), project, site, form, dates (the API also takes gender). Coded total; top 10 causes (age filter); main cause groups (age filter); age and sex table; causes by category/subcategory/disease per age scope with M/F/U/total; dropped CODs (unmatched ICDs). The export CSV is row level (SID, exact age, sex, COD), with no staff identity and no suppression. Bad dates and an unknown scheme answer 400 (digitva-208a, fixed). Built (digitva-3f72): the Causes tab shows everything above except the heatmap, treemap, age pyramid and sex pie; the form is a typed id because no endpoint lists forms; `age` in the URL is a view of the payload's `age_filters`, not an API filter.

## Users access view

Expo `/users` lacks every data manager write: create a user with an initial grant; look up an account by full email or mobile; grant at project/site/unit with cadre and default roles; revoke or reactivate grants; edit job title and languages; resend verification; issue the 72 h sign-in code. Backed by `/data-management/api/*` (data_manager, admin). Owner 2026-10-24: not now; Expo Users links to the Flask page.

## Mentor view (digitva-oux5, handed over by the Bugfixes session)

Owner decisions as relayed 2026-10-24: per coder in one district (viewer picks): ready for them, coded (period), reviewed agreed vs changed, not codeable, recodes, last active; read-only drill-down of that coder's coded cases (case id, date, final COD summary, review outcome) opening the existing read-only view. Viewers: mentor-institute staff for attached depth-1 units (`mas_mentor_institute`, `map_mentor_institute_org_unit`, `map_mentor_institute_user`) plus district data_manager and In-charge; coder-only gets 403. v1 feedback: a note (<= 2000 chars, no-PII warning) on a coder's coded case; the coder sees it on the case and in "Feedback from mentors" on Home and marks it read; append-only, the author may retract (soft delete, audited). Additive migration on the committed head. Policy first (`docs/policy/mentor-view.md`), security review before merge. Why the area per-coder table was removed: `docs/policy/area-dashboard.md:80-92,188-190`.

## Owner decisions 2026-10-24

- Users access view: not now.
- Admin: add `admin` to the data manager list, card, chart, export and sync API decorators (digitva-ujbi), so admin sees all Data screens across projects.
- Mentor view: decisions confirmed as relayed, notes in v1.

## Related bugs found by the audit

digitva-10fd (P1 coded_by sort leak), digitva-208a (cod-buckets 500), digitva-i347 (SmartVA failed field), digitva-ujbi (admin vs API decorators), digitva-l945 (card/list mismatch), digitva-4xpd (days param 500), digitva-d92d (sync runs limit before scope).

## Order

1. jv14 fix-ups (running). 2. digitva-208a, digitva-i347, digitva-10fd (backend, small). 3. 3f72 Data: Overview, then Causes, then Pipeline. 4. oux5 policy, then backend and migration, then the 3vj8 screen. Users access view: deferred.
