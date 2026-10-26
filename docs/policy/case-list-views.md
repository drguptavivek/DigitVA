---
title: Case List Views Policy
doc_type: policy
status: proposed
owner: Vivek Gupta
last_updated: 2026-10-26
---

# Case List Views Policy

Bead `digitva-yeg3.24` (epic `digitva-yeg3`, workflow UX audit 2026-10-20);
Supervision preset `digitva-a5jf`.

## Purpose

No screen today follows one death from report to coded. Register states
(`VaDeathRegister.status`) show only in Supervision; workflow states show only
in the data manager dashboard (ODK submissions). This policy defines one case
list, one row per death, that spans both, and the navigation that reaches it.
It adds no new right: every row and field is gated by the existing grants
(`access-control-model.md`).

## Decisions

Owner decisions, 2026-10-20.

1. **Navigation** is Home, Deaths, VA Interview, VA Code, VA Review,
   Statistics, More (Organization, Settings, Website). Wide screens show only
   a left menu; mobile shows only a bottom bar. Items a user has no role for
   are left out (see `expo-client.md`, "Role home").
2. **Deaths, VA Interview, VA Code and Supervision are presets of one shared
   case list**: one row per death, one API, one Expo component. They share
   columns and filters and differ only in default filter, sort and primary
   action:

   | Preset | Default filter and sort | Primary action |
   | --- | --- | --- |
   | Deaths | all reported deaths in scope | Add a death |
   | VA Interview | adds interview status; defaults to cases needing an interview | Start / resume interview |
   | VA Code | adds coding status; defaults to cases awaiting or in coding | Open for coding |
   | Supervision (the Deaths tab's supervisor preset, decision 7) | "Needs my decision", oldest first; includes duplicate and cancelled cases | by reason (see "Supervision preset") |

   A preset only pre-fills filters and the action; the user may change any
   filter. Statistics is the area dashboard (`area-dashboard.md`), unchanged.
3. **Server-side scope.** Project, site and unit scope are enforced from the
   authz services. Form-, site- and project-level access are not
   interchangeable. A client filter never widens scope.
4. **Mobile filter UI follows iOS HIG**: a filter button opens a bottom sheet
   with grouped options; applied filters show as chips; "Clear all" resets.
5. The data manager CSV export uses the same scope and filters as the list.
6. **Field roles see location** (revised 2026-10-20). In **organization**
   projects interviewers and death reporters have PII access and need the
   GPS fix to reach the household. The case GPS (`latitude`, `longitude`)
   may therefore be carried **in the case rows** (`GET /intake/cases`) and
   shown as a **map-pin button on the card** (and as the "Open in maps" link
   on the detail), **only for callers whose role or project has PII access
   for that case**, decided by the same authorization and redaction
   predicates (`should_redact_pii`) as the contact details on the case
   detail. Never for supervisors without PII access, coders, reviewers or
   data managers without PII access: those rows omit the fields (not blanked).
   In **non-organization (sites-mode)** projects the rows never carry
   coordinates, even for interviewers. The **case detail** and the
   register lists (`GET /intake/cases/<id>`, `GET /intake/deaths`) follow
   the same rule (owner, 2026-10-20), with one addition: the caller's
   **own registration** always keeps its fix, in any project, because the
   registration edit form reads it from there and its reporter captured it.
   Where the rule withholds the fix, `latitude`, `longitude`, `accuracy_m`
   and `captured_at` are omitted (not null); a correction that omits them
   keeps the stored fix, so nothing is lost.
   "Organization project" is a project with an active organization level
   (`projects_with_org_tree`), the notion intake scope checks use.
   Coordinates are personal data: never logged, never in exports, and never
   in the supervision rows (the Deaths supervisor preset keeps them out
   unless the same predicate grants PII). The map link is **built on the
   client** from the two numbers; the server sends no URL. Accuracy and
   capture time stay on the detail only.
7. **Supervisors work in the Deaths tab only** (owner answer, 2026-10-20).
   There is no separate Supervision screen or menu item: `/supervision`
   becomes a redirect to the Deaths tab with the supervisor preset applied.
   The supervisor tiles and segments (see "Supervision preset") appear in the
   Deaths tab **only for users with supervision scope**
   (`supervised_case_condition`). Data managers keep their Data management
   screen.

## Deaths list, first step (owner, 2026-10-20)

Implemented before the API above: the Deaths screen
(`/death-registration?view=mine`) and VA Interview's Reported deaths tab show
one shared list over the existing `GET /intake/cases`.

- Scope: the interviewer worklist plus, for a `death_reporter`, the deaths it
  registered that its reporter grant still reaches (what `GET /intake/deaths`
  already lists it). No role sees more than before. A row reached only as
  reporter carries `can_interview: false`, no other-draft warning, and offers
  Edit only (prefill from the reporter's own list, never the case detail).
- Filter bar: search; then status chips left (All, To visit, In progress,
  Submitted) and toggles right: Mine | All (`registered_by_me`, default Mine
  only for a user whose one death role is `death_reporter`) and Last 30 days |
  All (date reported, client side, default All). Project and Area move into
  Advanced filters, first; applied ones stay removable chips with the count.
- Cards: name as title (else ID), the ID once, a status badge, one primary
  action (Code now, Resume, Start interview, Edit, View).

## Supervision preset (owner, 2026-10-20, `digitva-a5jf`)

The supervisor is the male or female health supervisor at a PHC who
supervises the ANM/MPW workers, clears queries with them about reported
deaths and eliminates duplicates. Supervision powers and their audit are
unchanged (web-intake.md, "Supervisors"); this preset only changes how the
supervisor's cases are listed. Per decision 7 it lives in the Deaths tab, not
on its own screen.

- **Default view:** "Needs my decision", oldest first.
- **Header count tiles**, each also a filter (tap to apply):
  - **Needs my decision**: a flag waiting for a supervisor
    (`pending_flag` set) or a second complete interview to choose
    (`_has_candidate`).
  - **Overdue revisits**: `next_visit_at` in the past on a case still open.
  - **Stuck**: an open case with no update for 30 days (`updated_at`).
  - **Total in scope**.
  - There is **no "Awaiting QA" tile**.
- **Segments:** the tiles above are the segments; the state chips (Not
  reachable, Refused, ...) and the visit-note chip are extra filters. A
  By-interviewer cut is not built.
- **Row:** id, age/sex, date of death, unit, state, reason badge,
  interviewer name, waiting time, registration numbers
  (`death-registration-identifiers.md`; values for roles allowed to see
  them, otherwise a has-number / missing badge). An **Add registration
  number** row action, which on cancelled and confirmed-duplicate cases is
  offered only to supervisors and the In-charge.
- **Actions:** one primary action chosen by the reason: **Resolve flag**,
  **Choose interview**, **Reopen**. An overflow menu holds **Cancel**,
  **Mark duplicate** and **Reopen for revision**. Each calls the existing
  supervision endpoint with its `X-CSRFToken` and reason; the list itself
  mutates nothing.
- **Includes duplicate and cancelled cases** by default, so a supervisor can
  find and reopen them; the other presets leave them out unless filtered for.
- **Privacy** as in web-intake.md "Privacy rule (item 14)": supervisors see
  identifiers in case-administration views; coding screens keep their
  redaction. The list carries no phone digits (a `has_informant_phone` flag only).
- **Entry:** the Deaths tab shows these tiles and segments only to a user
  with supervision scope; `/supervision` redirects to the Deaths tab with this
  preset applied; there is no Supervision menu item. A data manager keeps
  Data management.
- **Web only today:** `supervised_case_condition` returns no rows under
  device (bearer) credentials, so the preset is served to the browser shell
  only.

## Row contract

One row per `VaDeathRegister` case, built as `VaDeathRegister` LEFT JOIN
the case's submission/workflow state. Confirmed duplicates and cancelled
cases are left out unless the status filter asks for them or the preset is
Supervision (as in `area-dashboard.md`).

| Field | Notes |
| --- | --- |
| `death_id` | row key |
| name | `deceased_name`; per-row visibility, below |
| ID | `unique_id` |
| age / sex | `age_years` (or derived age), `deceased_sex` |
| date of death | `date_of_death` |
| date reported | `created_at` is when the case row was created, and the report time only for `source = 'register'`. For `direct` and `odk` cases it is when the interview started or the sync created the case. Every row carries `source`; the row field `reported_at` is `created_at` and is present only when `source = 'register'`, so the UI shows "Reported" from `reported_at` and labels `created_at` "Started" (`direct`) or "Received" (`odk`). Sorting and the `reported_*` filters stay on `created_at` |
| unit | org unit name (`MasOrgUnit.unit_name`); site name for site-mode projects; omitted on coder-only rows until open question 2 is answered |
| status | one combined code, below |
| registration numbers | per `death-registration-identifiers.md`: `[{code, label, value}]` for roles with PII access in the case's project and `collaborator_pii`; `[{code, label, present}]` (has number / missing badge, no value) for everyone else, including coders, reviewers and coding testers. Values are stored encrypted and decrypted only for the rows on the page and only for viewers allowed to see them |
| `latitude`, `longitude` | decision 6: only where the caller has PII access for the case; omitted otherwise; never in supervision rows or exports |

Combined status, derived on the server from the register status and the
workflow state, in this order of precedence (first match wins):

`reported` (registered, no interview started) -> `interview_pending`
(scheduled, not reached, paused counted separately only if the owner wants it;
see Open questions) -> `interview_in_progress` -> `submitted_awaiting_coding`
(`ready_for_coding` and earlier pre-coding states) -> `in_coding`
(`coding_in_progress`, `coder_step1_saved`) -> `coded` (finalized) -> terminal
(`refused`, `not_codeable`, `duplicate`, `cancelled`).

The mapping is **one SQL `CASE` expression** built by one server function and
reused for the row, the status filter and the counts, so the three never
disagree. `Pending Coding` keeps the data manager meaning
(`data-manager-workflow.md`): coder-actionable states only.

## Filters and controls

Project, site/unit (subtree), status, date-of-death range, reported range,
reporter / interviewer / coder, has / missing registration number (any type
or one type).

- **Has / missing registration number** is served from the existence of a
  `map_death_identifier` row (`EXISTS`), never by decrypting; counts use the
  same predicate. Available to every role that sees the badge.
- **Search by registration number** is exact match only, through the blind
  index (`death-registration-identifiers.md`, "Blind index"), and only for
  users allowed to see values.
- **As built (digitva-kzyp stage 3 backend).** `identifier=has|missing` with
  optional `identifier_type=<code>` (the existence rule above, counts included;
  tiles ignore every filter, as for the other filters) and
  `identifier_number=<text>` (normalised as on a write, at most 256
  characters, matched by blind index per active type, only on rows whose values
  the caller sees; anything else matches nothing without saying why; counted
  against its own per-user `IDENTIFIER_SEARCH_RATE_LIMIT`, default 120 an hour,
  apart from the 30 an hour of the register / correct / write requests that
  carry numbers; the search reads every active type, none is left out). Each row carries
  `can_edit_identifiers`, which drives the **Add registration number** action.

- Every option list (projects, sites, units) is limited to the user's
  granted scope, resolved server-side. An id outside scope narrows the list
  to no rows; it is never echoed.
- Dates are ISO dates, validated at the boundary; range end is inclusive.
- **"Last 30 days" is a client preset** that sets `reported_from` to today
  minus 30 days (local date, today included); the server has no `last_days`
  parameter.
- Person filters take user ids from the scoped option list; a user sees
  another person's name there only where the role may see staff identity.
- Mobile: filter button -> bottom sheet with grouped options (Status,
  Dates, Place, People), applied-filter chips under the header, "Clear all".
  Wide screens may show the same controls inline.

**Already built** (`src/web/caseFilters.tsx`; `docs/current-state/expo-client.md`)
and reused by the shared list: tabs; search; status chips; Mine | All and
Last 30 days | All toggles; Project and Area inside Advanced filters;
advanced filters for date of death, date reported, sex and age band; applied
filters as removable chips with Clear all. Today only Project runs on the
server and the rest filter loaded pages; the shared list moves them into the
server query.

## Scope and field visibility

**Rows** are the OR of the existing per-role predicates, evaluated in one
query; no new scope rule:

- `_worklist_scope(user, roles=DEATH_REGISTERING_ROLES)`
  (`app/services/web_intake_service.py`): an interviewer's or death
  reporter's reach. It already decides interviewer visibility: the **whole
  unit subtree** of their unit grants (the project-site for a wider grant),
  not only cases they started.
- `supervised_case_condition(user)` (`app/services/authz/supervision.py`):
  cases the user supervises.
- the submissions `scope_filter(user, action)`
  (`app/services/authz/predicates.py`), through the case's `va_sid`: coding,
  data manager and collaborator reach.

Not `authz.reachable_unit_ids`: it answers "which units", not "which cases
this role may see", and would merge reaches that are not interchangeable.

**Empty scope returns `[]`** with zero counts and 200, never 403.

**Field visibility is decided per row**, in the same SELECT, by labelled
boolean columns (for example `via_field`, `via_supervision`, `via_coding`),
one per predicate above. A user who reaches a row through several predicates
gets the widest fields any of them allows. Hidden fields are omitted from the
payload, not blanked in the client. Cells marked **Q** are open questions.

| Reach | Tier (Inside vs Outside Health System) | Name & Registration Numbers | ID, age/sex, dates, unit | Status | Reporter / interviewer / coder |
| --- | --- | --- | --- | --- | --- |
| admin | Global | yes | yes | yes | yes |
| in-charge (`in_charge` / unit leader) | Tier 3 (Inside health system) | **yes (PII)** | yes | yes | yes |
| unit `data_manager` (`org_unit` scope) | Tier 3 (Inside health system) | **yes (PII)** | yes | yes | yes |
| `interview_supervisor` | Tier 3 (Inside health system) | **yes (PII)** (supervises cases) | yes | yes | yes |
| `interviewer` (unit subtree) | Tier 3 (Inside health system) | **yes (PII)** | yes | yes | self only |
| `death_reporter` (cases it registered) | Tier 3 (Inside health system) | **yes (PII)** | yes | yes | self only |
| in-system `coder` / `reviewer` (within-tree or cross-tree health unit, or self-coding) | Tier 3 (Inside health system) | **yes (PII)** | yes | coding status | self / unit |
| `project_pi` | Tier 1 (Outside — Project level) | **no (Non-PII)** | yes | yes | no |
| project `data_manager` (`project` scope) | Tier 1 (Outside — Project level) | **no (Non-PII)** | yes | yes | no |
| `site_pi` (Mentoring Institution / external site PI) | Tier 2 (Outside — Mentoring Inst) | **no (Non-PII)** | yes | yes | no |
| mentoring / external `coder` / `reviewer` / `coding_tester` | Tier 2 (Outside — Mentoring Inst) | **no (masked coding, Non-PII)** | `unit_name` omitted | coding status | no |
| `collaborator` (Project or Mentoring Inst viewer) | Tier 1 / Tier 2 (Outside) | **no (Non-PII)** | yes | yes | no |

Rules that are decided:

- Coders and reviewers code masked; the shared list must not leak identity
  to them. Until the owner answers, a coder-only row returns no name and no
  unit name.
- Location follows decision 6: `latitude` and `longitude` are in the rows
  and on the card's map-pin button, and on the detail, only where the
  caller's role or project has PII access for the case (interviewers and
  death reporters in organization projects); omitted for every other
  reach, and in sites-mode projects for everyone. The detail and the
  register lists apply the same rule but keep the caller's own
  registration's fix in any project (its edit form). Supervision rows stay without coordinates.
- Informant name, address and phones are never in the list (as in
  `serialize_worklist_row`).
- The CSV export carries the same columns the viewer sees, minus anything
  `data-manager-workflow.md` forbids in bulk extracts (PII payload fields,
  direct local identifiers), and the same filters.
- **Exception, registration numbers** (owner, 2026-10-20,
  `death-registration-identifiers.md` decision 9 and "CSV export"): the
  export includes one column per active identifier type **only when the
  exporter has PII access in that project**; the columns are omitted, not
  blanked, for any other exporter. Values are decrypted in memory per
  streamed batch, after a validation pass over the same batches: an unreadable
  number refuses the export (500 `export_unreadable`, no audit row, no body;
  owner, 2026-10-21). Each export that includes them writes one audit row
  (`map_identifier_audit`, `export_with_identifiers`: exporter, role, filter
  set, row count, type codes; never a value).

## API and service outline

Proposed; names follow `api-v1.md` conventions.

- **New service `list_cases`**, modelled on `_worklist_select`
  (`app/services/web_intake_service.py`): one SELECT carrying the case, unit
  name, workflow state, the per-row visibility labels and the combined
  status `CASE`. Not built on `list_supervised_cases`, whose scope is
  supervision only.
- **`GET /api/v1/intake/deaths` stays untouched**: the registration edit
  form's prefill reads it (`expo-client.md`: Edit opens
  `/death-registration?deathId=` and reads `GET /intake/deaths`).
- `GET /api/v1/cases` with query: `preset`
  (`deaths|interview|coding|supervision`), `project_id`, `site_id`,
  `org_unit_id`, `status` (repeatable), `dod_from`, `dod_to`,
  `reported_from`, `reported_to`, `identifier` (`has`|`missing`),
  `identifier_type`, `identifier_number`, `cursor`, `limit`. Returns
  `{cases, counts, next_cursor}` with `counts` per combined status (and the
  Supervision tiles) ignoring the status filter, as `list_supervised_cases`
  does, computed with the same `CASE` in one aggregate query.
- `GET /api/v1/cases/filter-options`: scoped projects, sites, units.
- `GET /api/v1/cases/export.csv`: same query, same scope; data managers
  only (`data_manager`, `admin`). Registration number columns and their
  audit as under "Scope and field visibility".
- Read-only GETs; the list triggers no mutation. State changes keep their
  existing endpoints and `X-CSRFToken`.
- Keyset paging on `(created_at, death_id)` when sorted by reported date
  (index `ix_va_death_register_created`), on `(updated_at, death_id)`
  otherwise (`ix_va_death_register_updated`). Limit is clamped server-side
  (`WORKLIST_PAGE_MAX`). Cursors are opaque and validated.
- One query for the page: joins for unit, reporter and workflow state in the
  same statement, aggregate counts in the database, no per-row lookups.
- **Merge gate:** `EXPLAIN (ANALYZE, BUFFERS)` of the page query and the
  counts query on the staging dataset, with index use or scans recorded. The
  counts query (OR of three scopes, no `LIMIT`) is the expensive one.
- The Expo component is a rework of `SupervisionScreen.tsx` into a shared
  `CaseListScreen`; the Supervision preset keeps its flags and visit-note
  filters as extra chips.

## Non-goals

- No change to who may start an interview, code, review or supervise; the
  list only shows, links and calls existing endpoints.
- No case editing in the list; row tap opens the existing detail.
- No new roles, grants or scope kinds.
- No cross-project merged statistics (that is Statistics).
- No free-form export of PII. Registration numbers are the one exception,
  limited and audited as above.

## Open questions

1. Name visibility per role (table cells marked Q): may project_pi, site_pi,
   data_manager, collaborator see the deceased name in the list, or only
   `collaborator_pii` and field roles?
2. Do coders and reviewers see ID, age/sex, dates and unit, or only an
   opaque id plus coding status?
3. Are "scheduled", "not reachable" and "paused" shown as `interview_pending`
   or kept as separate statuses?
4. Where does "VA Review" fit: another preset of the same list, or its own
   screen?
5. Free-text search (name, ID) and its index cost, if wanted.
6. Is the reporter / interviewer / coder filter shown to roles that may not
   see staff identity? Deferred: the person filters (`reporter_id`,
   `interviewer_id`, `coder_id`) are not built.
7. How are sites-mode projects (no org tree) labelled in the unit column?
   The people options of `filter-options` are deferred with Q6.

## Backend implemented (digitva-pt0s, 2026-10-20)

Status stays `proposed` until the owner answers the open questions. The shared
service (`app/services/case_list_service.py`) and `GET /api/v1/cases` and
`/cases/filter-options` exist (`docs/current-state/api-v1.md`, "Case list").
Not built: the Expo `CaseListScreen` (digitva-kzyp stage 4). **Stage 5 implemented:** `GET /api/v1/cases/export.csv` (`docs/current-state/api-v1.md`, "Case list"), with the registration-number exception above.
The registration-number row fields and filters are built (stages 2 and 3 backend):
`identifiers` on every row, values per the per-row `can_identifiers` test, `can_edit_identifiers`,
the has / missing filter and the exact number search. Defaults applied, **owner-pending unless marked decided**:

1. Names and PII (**updated by owner decision 2026-10-26, `digitva-ewa5`**; see
   [Access Control Model](access-control-model.md), "The Three-Tier Mental
   Model & PII Boundary"):
   - **Inside the health system (Tier 3 — All PII):** **In-charge**, unit-scoped
     `data_manager`, `interview_supervisor`, `interviewer`, `death_reporter`
     (own registrations), and **in-system `coder` / `reviewer`** (whether
     coding within-tree on their home unit or cross-tree on sibling health
     units, or in a self-coding project) see PII (deceased name, unit, and
     registration numbers per role rules) across their granted scope.
   - **Outside the health system (Tier 1 Project level & Tier 2 Mentoring
     Institution — All Non-PII):** `project_pi`, project-scoped `data_manager`,
     `site_pi` (Mentoring Institution PI), mentoring/external `coder`,
     `reviewer`, `coding_tester`, and `collaborator` **do not see PII** (names,
     staff identity, GPS and registration number values are omitted). If an
     external person exceptionally requires PII access, they are placed in
     Tier 3 and granted `data_manager` at the District (`org_unit`) level.
   - Admin remains a PII holder (owner, 2026-10-21) with no scope bypass.
2. Coders and reviewers see `unique_id`, age/sex, dates and status; no name,
   no `org_unit_id`/`unit_name`. Collaborators, PIs and data managers see the unit.
3. `scheduled`, `not_reachable` and `paused` all map to `interview_pending`;
   the register state stays in `register_state` and the `state` filter.
4. No separate VA Review preset; presets are `deaths`, `interview`, `coding`,
   `supervision`.
5. No free-text search (no `q` parameter).
6. Person filters (and the `people` part of `filter-options`) are deferred and
   not built (Q6, Q7). Reporter, interviewer and coder names in rows follow
   staff-identity visibility.
7. A sites-mode project's unit column carries the site name (`unit_name`).
8. Also decided here: `draft_identity` counts as `interview_in_progress`; a
   `submitted` case with no workflow row is `submitted_awaiting_coding`;
   `consent_refused` is `refused`; `reviewer_coding_in_progress` is
   `in_coding`; `counts` include duplicate and cancelled in every preset;
   date filters are UTC days (the client's "last 30 days" is a local date);
   admin reaches only cases with a submission (no admin bypass in the interviewer
   and supervision rules).
9. `created_at` is the report time only for `source = 'register'`; rows carry
   `source` and `reported_at` (register cases only). See "Row contract".
10. `counts` and `tiles` are computed on the first page only (no `cursor`);
   a reply to a request with a `cursor` omits both keys, because they are
   sequential scans (`docs/kb/case-list-query-plans.md`).
11. Two different metrics: Home "Deaths I registered" counts
   `registered_by = me` and `source = 'register'`; this list's Deaths preset
   counts the caller's whole scope across every source. Home's query is
   untouched; the two numbers are not expected to match.
12. Native-token caveat: `supervised_case_condition` returns nothing under
   bearer (device) credentials, so the supervision preset and the tiles are
   web-session only. A client must not show the supervisor view from browser
   roles when the token is native.

## Rollout

- No schema change expected for the list. Existing indexes on
  `va_death_register` (`date_of_death`, `created_at`, `updated_at`,
  `next_visit_at`, `org_unit_id`, `registered_by`, `project_status`) cover
  the filters and tiles.
- Possible additions, only if the plan shows scans: an index for the
  workflow join (`va_sid`) and for coder/interviewer filters. Any such index
  ships with an additive migration; check `flask db heads` before and after.
- Order: this baseline, then `list_cases` and the API with scope tests, then
  the Expo `CaseListScreen` and navigation, then the CSV export. Update
  `docs/current-state/api-v1.md` and `expo-client.md` with the
  implementation, and `docs/policy/expo-client.md` "Role home" for the new
  navigation.
- Tests: scope per role (assert the subject is present, then that the
  out-of-scope row is absent); a user reaching one row through two
  predicates gets the wider fields; empty scope returns `[]` with 200; field
  omission per role; each filter; combined status equal in rows and counts;
  Supervision tiles and default sort; duplicates and cancelled present in
  Supervision and absent elsewhere; cursor continuity; export parity with
  the list; query count constant in page size; `GET /intake/deaths`
  unchanged.
