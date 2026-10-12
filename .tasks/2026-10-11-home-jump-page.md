# Role home on the Expo web app

- Status: approved (owner, 2026-10-11 and 2026-10-12), not started
- Priority: P2
- Created: 2026-10-11
- Beads: `digitva-umc4` backend; `digitva-k6i9` Expo role home;
  `digitva-xqta` Expo supervision screen; `digitva-b3pt` area view deaths
  reported; `digitva-qu7x` home KPIs; `digitva-e7sz` organization page;
  `digitva-qirs` Expo DM screen (deferred)

## Goal

After login, each field and coding user lands on the screen they work in,
with nothing to read first. Roles are mostly disjoint (dev, 2026-10-11: 87
coder-only, 8 interviewer-only, 17 users with more than one role, mostly PIs
and In-charges, who also derive data_manager and interview_supervisor). Web
only (Expo export at `/app/`); the native device app keeps its worklist.

## Owner decisions

- 2026-10-11: web only; all six roles land on the new home; no counts.
- 2026-10-12: the coding screen shows the number of cases waiting for
  coding, in every project and both modes (the existing queue stats).
- 2026-10-12: the home carries the real role screens, not jump buttons. A
  supervision screen is built in Expo now. The data manager screen is
  deferred: data managers keep the server-rendered `/data-management/` page.

## What each role needs (owner, 2026-10-12)

- Death reporter (ANM, MPW): report a death; see the deaths I reported.
- Interviewer (CHO, SN): see the deaths reported for VA; start a VA directly.
- Supervisor (CS, SMO, PHC MO): see the deaths reported; reconcile
  duplicates; read visit notes (the owner's "field notes").
- Coder (MO): see that VAs are waiting for coding, and code.
- Reviewer: see what waits for review, and review.
- Data manager (DPM, BPM): deaths, VA status and coding status within
  their area.

## Shape

- One role: `/app/` renders that role's screen directly.
- More than one role: the same, with a strip of role tabs on top. The last
  tab used is remembered per browser (localStorage, convenience only).
- Login: every user holding one of the six roles (data_manager included)
  lands on `/app/`. A data manager's tabs there are "Area" and "Data
  management", which open the server pages `/area/` and
  `/data-management/`.
- Last visit wins (owner, 2026-10-12): the browser remembers each user's
  last visited screen (localStorage, keyed by user id; role screen or one of
  the server pages above). On the first `/app/` load after a sign-in
  (a sessionStorage flag), the app goes straight there; later visits to
  `/app/` show the home. Nothing stored, or storage unavailable: the role
  screen. The server-side `landing_page` preference no longer applies to the
  six roles.
- Roles outside the six (admin, project_pi, collaborator) keep today's
  landing.

## Role matrix (TST001 roster, `docs/current-state/test-project-tst001.md`)

| Cadre, unit | Roles | `/app/` shows |
|---|---|---|
| ANM, MPW (sub-centre) | death_reporter | Death registration |
| CHO (sub-centre), SN (DH, CHC) | interviewer | Collection: reported deaths worklist, Start VA (direct intake projects) |
| MO (PHC) | interview_supervisor, coder | tabs: Coding, Supervision |
| SMO (CHC) | interview_supervisor, reviewer | tabs: Supervision, Reviewing |
| CS (DH) | interview_supervisor | Supervision |
| MO (DH, CHC) | coder | Coding |
| MO (DH), reviewer grant | reviewer | Reviewing |
| DPM (DH), BPM (CHC), project DM | data_manager | login goes to `/area/` |
| In-charge (`site_pi` at a unit) | derives data_manager, interview_supervisor | tabs: Supervision, Area (+ Coding/Reviewing if granted) |
| DEPI, faculty, resident, PI, admin | outside the six | unchanged |

| Role | Screen | Exists? |
|---|---|---|
| coder, coding_tester | coding queue (`workspace/QueueScreen`) | yes; opens on the last project |
| reviewer | reviewing queue | yes; opens on the last project |
| interviewer | collection (`web/CollectionScreen`) | yes |
| death_reporter | death registration and my reported deaths | yes |
| interview_supervisor | supervision | **new** (`digitva-xqta`) |
| data_manager | Flask `/area/` | exists; gains deaths reported (`digitva-b3pt`); Expo screen deferred (`digitva-qirs`) |

## Coding and reviewing queues on the home

- Holding a case: Resume case comes first.
- The queue opens on the coder's last project: the project of the most recent
  coding `va_allocations` row; else the only project; else "All projects".
- Random mode with work: Start next case. Pick mode: the pick list. The
  waiting count shows for every project.
- Reviewer: same, from the most recent reviewing allocation; no modes.

## Supervision screen (Expo, `digitva-xqta`)

Parity with the Flask page, plus actions the API already has but the page
lacks. All calls use the browser session and `X-CSRFToken`; device bearer
tokens carry no supervisory powers.

- List: tabs "Flags to resolve" and "All cases", state filter, Load more
  (keyset cursor), the empty-scope text. Row fields as the Flask page
  (`app/static/js/intake/intake_supervision.js`).
- Row actions: confirm or reject a flag, mark duplicate (kept-case picker:
  same project, not duplicate, cancelled or draft_identity), cancel, reopen.
  Reason where the API requires it, at most 200 characters, with the "no
  names, phone numbers or addresses" warning.
- Case detail (new to supervisors): `GET /supervision/cases/<id>`, showing
  interview candidates for a submitted case and **Choose interview** with the
  API's reason codes.
- **Reopen for revision** on a submitted case (API exists).
- **Possible duplicates** on the case detail, so a supervisor sees matches
  before marking a duplicate. Needs the new endpoint below.
- **Visit notes**: a "Visit notes" filter on the list and the note on the
  case detail, redacted for viewers without PII access as everywhere else.

Not in scope: case history, contact attempts, reassignment (policy: a
supervisor never assigns, `docs/policy/web-intake.md`).

## Backend (`digitva-umc4`, outside `mobile/`)

- `VaUsers.landing_url()`: the login rule above; the old logic stays for
  other roles. `tests/routes/test_collaborator_viewer_access.py:249`
  asserts the old landing and must be updated.
- `GET /api/v1/coding/projects` and the reviewing equivalent return
  `last_project_id`.
- `intake.new_death_page` also allows `death_reporter`; the API already does.
- `GET /api/v1/intake/supervision/cases/<death_id>/possible-duplicates`:
  `possible_duplicates(..., scope=supervised_case_condition)`. The reply is
  limited to supervisor-row fields (no informant name or village) unless the
  policy says otherwise.
- Supervision visit notes: `visit_note` on the supervisor case detail via
  `visit_note.visit_note_for_viewer`, and a `visit_note=1` filter on
  `GET /supervision/cases` using `has_visit_note_condition`.
- Policy first: `docs/policy/expo-client.md` (role home, landing) and
  `docs/policy/web-intake.md` (supervisor possible duplicates and visit
  notes).
- Tests: landing per TST001 roster row (the matrix above); `last_project_id`
  for a coder with a random and a pick project; the supervisor duplicates
  endpoint returns nothing outside the supervisor's reach and 404s for a
  case outside it.

## Expo (Expo session owns `mobile/`)

Build only from the shared components already in use (owner, 2026-10-12);
no new look and no parallel primitives:

- Shell and layout: `WebShell` and `browserErrorText` (`src/web/common.tsx`),
  `Screen`, `Button`, `Row`, `useUiStyles`, `stateLabel` (`src/ui.tsx`).
- Choices and inputs (reasons, reason codes, filters): the WHO interview
  controls `WhoVaQuestionControls` from the vendored WHO VA package, as the
  coder panels do (`docs/current-state/coder-component-inventory.md`).
- Lists and cases: the patterns of `workspace/QueueScreen.tsx`,
  `web/CollectionScreen.tsx` and `web/newCaseDetailScreen.tsx`; case history
  later through `workspace/WorkflowHistory.tsx`.
- Data calls: `workspace/api.ts` with `transport.web.ts` (CSRF), as the
  queues do.

A component the screens need and none of these supplies goes into the shared
set (`src/ui.tsx` or the workspace folder) for every screen, not into one
screen.

All UI text goes through the Expo i18n (`t()` keys in
`src/strings/en.json`, drafts in `hi`, `pa`, `mr`, `kn`, `ta`, `ml`, `te`, `gu` and `or` (`digitva-1g1h`)); no literal strings in
components (owner, 2026-10-12).

- `digitva-k6i9`: `/app/` renders the role's screen, role tabs for more than
  one role; QueueScreen accepts and defaults to a project.
- `digitva-xqta`: the supervision screen above.

## Area view (`digitva-b3pt`)

`/area/` already counts VA submissions, coding buckets, drafts in progress,
final COD and visit notes per unit and site. Add "deaths reported":
non-duplicate `VaDeathRegister` rows per unit and site, one grouped query
beside `_drafts_by_unit`.

## Home KPIs (`digitva-qu7x`, owner 2026-10-12)

A strip at the top of `/app/` for every one of the six roles, over the
user's own tree (the union of their grant roots, as `/area/` resolves it):

- **Deaths reported**: cases in the death register, all sources, excluding
  duplicates and cancelled cases. Every VA that arrives from ODK without a
  case gets one (owner, 2026-10-12; `digitva-l8y3`, a new `odk` source), so
  this counts every death the system knows and interviews (%) never passes
  100%.
- **Interviews done (%)**: completed VA submissions, as a percentage of
  deaths reported.
- **Coded (%)**: submissions with a final COD, as a percentage of deaths
  reported (owner, 2026-10-12).

Reuses `area_dashboard_service` (submissions from the materialized view,
`_final_cod_by_unit`) plus the deaths-reported count of `digitva-b3pt`. One
call, grouped queries, cached briefly per user. Blocked by `digitva-b3pt` and `digitva-l8y3`.

## Organization page (`digitva-e7sz`, owner 2026-10-12)

A dedicated page, not a home tab, linked from the user menu. Org projects
only.

- **Where I am**: my unit, level and cadre.
- **Above**: the chain of units up to the district, each with its people.
- **My level**: the people at my own unit.
- **Below**: the child units of my unit, one level at a time, each with its
  people on opening.

People are the unit's worker roster (`MasOrgUnitWorker`, including staff
who never log in), shown by name and cadre only: no phone, no email, no
address. Any user with a grant in the project may see the names (owner,
2026-10-12: people in an organization tree know each other, so name and
cadre disclose nothing new to them). Worker names are personal data
(`docs/policy/organization-model.md`), so this exception goes into that
policy first.

