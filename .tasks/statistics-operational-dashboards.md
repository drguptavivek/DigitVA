# Statistics as operational dashboards (proposal, awaiting owner)

- Status: design decided, implementation not started
- Priority: high
- Created: 2026-11-04
- Goal: Replace `/app/statistics` (one sentence of counts plus a bar list) with
  calm operational dashboards: tabs Overview, Deaths, Interviews, Codings,
  Projects; filters on top; case tables with overdue highlights.

## Current state

- Screen `mobile/digitva-collect/src/web/StatisticsScreen.tsx` (+ `src/web/stats/`),
  client `src/area/api.ts`, API `app/routes/api/area.py`
  (`/api/v1/area/{projects,summary,staff}`), service
  `app/services/area_dashboard_service.py`, policy `docs/policy/area-dashboard.md`.
- Scope: `resolve_area_scope` (area scope = unit subtrees via
  `authz.reachable_unit_ids`, or sites in sites mode). Any grant opens it.
- Policy today: "Counts only. No case lists and no subject data."
- Every interview has a `va_death_register` row (`source` = register /
  direct / odk), so one table covers reported deaths and direct interviews.
- `GET /api/v1/cases` (`case_list_service`) already builds the row shape,
  combined status, keyset paging and the per-row `can_name` / `can_staff`
  gates, but over the *work* scope, not the area scope. Rows lack submission
  date and coded date.

## Access rules (owner, 2026-11-04: names for PII users only)

- Rows and counts use the same scope: `resolve_area_scope`, so a table
  always reconciles with the counts above it.
- Deceased name: sent only when `should_redact_pii(user)` is false; otherwise
  the column is absent (not blank, not pseudonymised). Sealed names open
  through `register_pii_accessor.open_register_pii(..., only=("deceased_name",))`
  for the page only.
- Reported by / interviewer / coder are staff identity: existing `can_staff`
  gate (PII access plus admin, supervising role or data-manager lens).
- Rows are read-only. A row opens the existing case page only where the
  user's role already admits them; viewing scope never implies coding scope.
- CSV stays aggregates only (no case-level export from this page).

Policy change to approve with the design (`docs/policy/area-dashboard.md`,
"What it shows"): "Counts and read-only case tables over the same viewing
scope. The deceased's name only to viewers `should_redact_pii` does not
redact; staff names only under the staff-identity gate."

## Filters (top of every tab, in the URL)

- Project: multi-select (All, or any subset of `area/projects`).
- Period: Last 30 days, 90 days, 12 months, All time (as now).
- Area: the existing unit/site drill as one dropdown (district and PHC users
  depend on it), shown when one project is selected.
- Tab-specific, at most two: Deaths: Status, Source (reported / direct);
  Interviews and Codings: Status, Overdue only.

Period anchors: Deaths by date reported (as `deaths_reported` today);
Interviews and Codings by submission date. Backlog states (pending,
awaiting coding) stay current-state, never period-filtered.

## Tabs

```
[Project: All ▾] [Last 90 days ▾] [Area ▾]            (sticky filter row)
 Overview | Deaths | Interviews | Codings | Projects
```

- Overview: one stage strip, Deaths -> Interviewed -> Coded, with the
  number under each (owner, 2026-11-04: from `GET /api/v1/cases/stage-counts`,
  each number a tab's total; Deaths = every known death, reported or
  interviewed), and an attention line under the strip:
  "12 deaths not interviewed after 60 days · 4 interviews not coded after
  15 days", each a link into the filtered tab. Below: the per-area rows
  (existing pipeline bars), medians per project, top causes (existing
  suppression), stations. No tiles grid.
- Deaths: counts row (Pending, Interviewed, Coded, Closed) as filter chips,
  then the table: ID, Name*, Age, Sex, Date of death, Facility, Reported by*,
  Status, Days waiting. (*gated.)
- Interviews: chips Awaiting coding, In coding, Coded, Not codeable,
  Refused (2026-11-04; the tab and Codings send `interviewed=1`, so a death
  refused before any interview is not listed); table:
  ID, Name*, Age, Sex, Date of death, Interviewed on, Interviewer*, Facility,
  Status, Days since interview.
- Codings: chips Not started, In coding, Coded, Not codeable; table: ID,
  Name*, Interviewed on, Coded on, Coder*, Status, Days to code; top causes
  below.
- Projects: one card per accessible project: the three stage counts, the
  two overdue counts (stage-counts, one request for every project),
  medians and freshness (the area summary). Tapping sets Project to that one and opens
  Overview. Nothing else new.

Status fold (from `combined_status_case`): pending = reported,
interview_pending, interview_in_progress; interviewed =
submitted_awaiting_coding, in_coding; coded = coded; closed = refused,
not_codeable. Duplicate and cancelled are left out, as in every count.

Overdue: deaths pending more than 60 days after date of death (date reported
when the date of death is missing); interviews not coded more than 15 days
after submission. Shown as the warning fill on the row plus text
("Overdue · 74 days"), never colour alone. Desktop: a real table; under
768 px rows fall back to `CaseCard`.

## API

Owner, 2026-11-04: reuse the existing APIs. What already exists:

- Counts: `GET /api/v1/area/summary` (any grant, area scope). Add only
  `overdue_interview` / `overdue_coding` counts.
- Deaths, Interviews, Codings tables: `GET /api/v1/cases` with presets
  `deaths`, `interview`, `coding` (name and staff gates, combined status,
  facility, keyset paging, status counts, CSV). Gaps, each a small change:
  `project_id` repeatable (one `IN`), `submitted_at` and `coded_at` on the
  row (two joins), an `overdue=1` filter.
- `GET /api/v1/data-management/submissions` also lists interviews, but is
  limited to data managers, collaborators and admin, so it cannot serve
  coders, interviewers or site PIs here.
- Scope caveat: `/cases` uses the work scope, not the area scope. For some
  roles the table may hold fewer rows than the count above it. If that
  matters, add an `area=1` scope option to `/cases` instead of a new endpoint.

Superseded draft (new endpoint, kept for reference):

- `GET /api/v1/area/cases?project=A&project=B&period=&unit=|site=&stage=deaths|interviews|codings&status=&overdue=1&cursor=&limit=`
  reusing `case_list_service` internals (row shape, combined status, keyset
  cursor, limit 50 / max 200) with the area-scope filter. Adds
  `submitted_at` (`va_submissions.va_submission_date`) and `coded_at`
  (`va_final_cod_authority.effective_at`, else `created_at`) by join, plus
  `overdue` and `days_waiting`. Status counts on the first page only.
- `GET /api/v1/area/summary`: add `overdue_interview` and `overdue_coding`
  counts. Multi-project: the client calls `summary` per selected project in
  parallel (projects are few; the Projects tab needs each anyway) and sums
  counts; medians and percentages stay per project (policy: never sum
  percentages).
- Index check: no index on `va_submissions.va_submission_date`; measure the
  overdue-coding query on staging-sized data before adding one.

## Thresholds

Default: constants `OVERDUE_INTERVIEW_DAYS = 60`, `OVERDUE_CODING_DAYS = 15`
in the service, sent to the client in the summary. Later, if wanted: two
integer columns on `va_project_master` (pattern `recode_window_minutes`),
with a migration and admin field.

## Owner decisions, 2026-11-04

- Overdue: 60 days from date of death; 15 days from interview completion
  (submission date).
- Audience: Statistics is the oversight view (data managers and the like).
  People see their own work in Collection (`/collection?tab=deaths`),
  Coding (`/coding?tab=history`) and Reviewing, not here.

What `/cases` gives each oversight role (checked in
`case_list_service._reach`): `data_manager`, `site_pi` (In-charge),
`interview_supervisor` and `project_pi` are supervising roles, so they reach
every register row in their area, pending deaths included, and see names
with PII access. A `collaborator` / `collaborator_pii` reaches only cases with
an interview (so pending deaths do not appear in the table for them), and only
`collaborator_pii` sees names.

Owner, 2026-11-04: collaborators (plain, `_pii`, mentors) also see reported
deaths with no interview, so they can see how many interviews are pending.
Change: in `case_list_service._reach`, collaborator grants also reach
register rows in their grant area (`authz.reachable_unit_ids`, read-only;
no interview, edit or identifier rights). Names unchanged: `collaborator_pii`
only. Check the other `/cases` callers a collaborator can open before landing.

Owner, 2026-11-04: interviewers, coders and reviewers follow their own work
in their three screens (`/collection?tab=deaths`, `/coding?tab=history`,
`/reviewing`), not Statistics. So the Statistics menu entry and Home button
(`statisticsAllowed`, `src/web/roleHome.ts`) move to oversight roles: data
manager, site PI, project PI, interview supervisor, collaborator(_pii),
admin. The API keeps refusing nobody (policy "Who sees it" text changes).
Gap seen: the Collection Deaths list (`GET /intake/cases`,
`src/web/DeathsList.tsx`) stops at "Submitted"; an interviewer cannot see
that a case was later coded. Owner, 2026-11-04: include it in this work
(add the coding state to `worklist_page` rows by one join to
`va_submission_workflow`; Coded / Not codeable status on the card).

## Decided (owner, 2026-11-04)

1. Thresholds fixed in code: `OVERDUE_INTERVIEW_DAYS = 60`,
   `OVERDUE_CODING_DAYS = 15`; a per-project setting later if needed.
2. No date of death: the 60 days count from date reported.
3. Deaths statuses: Pending, Interviewed, Coded, Refused, Not codeable
   (each its own chip); duplicates and cancelled hidden.
4. Policy change approved: write it into `docs/policy/area-dashboard.md`
   before the code.

## Files (expected)

`app/routes/api/area.py`, `app/services/area_dashboard_service.py`,
`app/services/case_list_service.py` (scope parameter), tests under
`tests/`, `mobile/digitva-collect/src/area/api.ts`,
`src/web/StatisticsScreen.tsx` split into `src/web/stats/*Tab.tsx`, i18n
strings, `docs/policy/area-dashboard.md`, `docs/current-state/expo-client.md`,
`docs/current-state/api-v1.md`. No migration unless decision 1 picks
settings. Verify with targeted pytest, Jest, `make check-web`, and the dev
page with a PII and a non-PII account.

## API contract for implementation (2026-11-04)

Constants (one definition, `app/services/case_list_service.py`, imported by
the area service): `OVERDUE_INTERVIEW_DAYS = 60`, `OVERDUE_CODING_DAYS = 15`.
"Today" is the server's UTC date.

Overdue definitions (same SQL in `/cases` and `/area/summary`):
- interview overdue: combined status in (reported, interview_pending,
  interview_in_progress) and `coalesce(date_of_death, created_at::date)` is
  more than 60 days before today.
- coding overdue: combined status in (submitted_awaiting_coding, in_coding)
  and the submission date (`va_submissions.va_submission_date`) is more than
  15 days before today.

`GET /api/v1/cases` (backward compatible; every new item optional):
- `project_id` repeatable (`project_id=A&project_id=B`, or comma list): `IN`.
  One value behaves exactly as today.
- `submitted_from`, `submitted_to` (dates): filter on the submission date;
  rows without a submission are excluded when either is given.
- `overdue=interview|coding`: the definitions above.
- Row fields added: `submitted_at` (ISO datetime or null), `coded_at` (ISO
  datetime or null: `va_final_cod_authority.effective_at`, else its
  `created_at`, only when an authoritative assessment id is set),
  `overdue` (`"interview"`, `"coding"` or null) and `days_waiting` (int or
  null: days since date of death / reported for interview overdue
  candidates, days since submission for awaiting/in coding, else null).
  Joined in the page statement; no per-row queries.
- Reach: `collaborator` and `collaborator_pii` grants also reach register
  rows in their grant area (project grant: the project; site grant: the
  site; org-unit grant: the unit subtree), read-only: no `can_interview`,
  edit or identifier rights from this reach, names still only via
  `collaborator_pii`, staff names unchanged (`can_staff`).

`GET /api/v1/area/summary`: `counts` (card and every row) gain
`overdue_interview` and `overdue_coding` (live, period-independent, the
definitions above); the reply gains
`thresholds: {"interview_days": 60, "coding_days": 15}`. CSV carries the
two new measures.

`GET /intake/cases` (`web_intake_service.worklist_page`) rows gain
`coding_status`: `"awaiting_coding" | "in_coding" | "coded" |
"not_codeable" | null` (null when the case has no submission), from the
same mapping as `combined_status_case`, one join.

Statistics menu: oversight roles only (data_manager, site_pi, project_pi,
interview_supervisor, collaborator, collaborator_pii, admin). The area API
itself is unchanged in who it admits.

## Contract additions (owner, 2026-11-04, after first build)

- `GET /api/v1/cases` `source=register|direct|odk` (repeatable or comma
  list, validated): `VaDeathRegister.source IN (...)`; counts follow it.
  Deaths tab: Reported = `register`, Direct = `direct,odk`.
- Rows gain `can_open` (bool) and `va_sid` (string, only when `can_open`):
  true when the row has a submission the caller may view
  (`scope_filter(user, Action.VIEW)` on that submission, or admin). Pending
  deaths (no submission) are always false.
- The Statistics row link uses the Data screen's View rule (Flask
  `/data-management/view/<sid>` for data manager or admin, `/coding/area/<sid>`
  for a viewer role); no link when `can_open` is false or the user has
  neither.
- `days_waiting` is never negative (`GREATEST(..., 0)`).
- Area dropdown on the case tabs lists every unit in the user's area, leaf
  units included.
