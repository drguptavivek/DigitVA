---
title: Web Intake Policy (WHO VA 2022 questionnaire in DigitVA)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-05
---

# Web Intake Policy

## Purpose

DigitVA can collect WHO 2022 verbal autopsy questionnaires in its own web
pages, using the vendored questionnaire package under `vendor/who-va-2022`,
as a second intake path next to ODK Central. This policy fixes how that path
is enabled, who may use it, how identifiers are assigned, and how a web
submission enters the workflow. Plan:
`docs/planning/who-va-2022-web-intake-plan.md`.

## Baseline

- **Project setting** `va_project_master.web_intake_mode`: `off` (default,
  ODK only), `direct` (questionnaire only), `death_register` (a death must be
  registered first, then the questionnaire starts from it), `both`.
- **Role** `interviewer` (fills questionnaires) is an explicit access grant at
  project, project-site or organization-unit scope, like every other role.
  At unit scope the cadre must have `can_fill_va_form` at that level (see
  [Organization Model Policy](organization-model.md)). Interviewers see only
  their own drafts and the deaths of their own scope.
- **Role gate vs scope.** `VaUsers.is_interviewer()` decides only whether a
  user may reach `/intake/` at all: it is true when the user holds an
  interviewer grant that resolves to a `va_forms` row (project or
  project-site scope) *or* an active interviewer grant at unit scope, which
  never resolves to a form. Which project, site and unit a questionnaire may
  actually be filled for is decided separately, by
  `web_intake_service.interviewer_context()` and `_require_scope()`. The role
  gate never widens scope. Listing deaths (`list_deaths`) follows the same
  reach as entry attribution: a project- or site-scoped interviewer grant
  sees every death of the project-site, unit or not, because that grant
  reaches every unit; a unit-scoped grant sees only deaths whose unit falls
  in its own subtree(s), so an unrouted (NULL-unit) death is invisible to it
  (`digitva-nrq`, 2026-09-29).
- **Death register** (`va_death_register`): deceased name, sex, ABHA number
  and ABHA address, date of birth or age, date of death, place, address,
  informant, remarks, unit. Name, phone and ABHA identifiers are personal
  data and follow the PII rules (never logged, admin-only exports).
- **Birth-date precision**: exact birth dates use `date_of_birth` (YYYY-MM-DD).
  Month/year and year-only values use optional `date_of_birth_partial`
  (YYYY-MM or YYYY), mutually exclusive with the exact date (both is
  refused). A partial value must be well formed, from 1900, and not after
  today or the date of death at the precision given (the month or year of
  death itself is accepted). Missing day or month is never fabricated in the
  register. Age may accompany a partial
  birth date or stand alone when birth date is unknown. WHO prefill uses
  `dob_precision`, `dob_month_year` or `dob_year` for partial values; WHO
  sentinel days stay confined to those precision fields, never `Id10021`.
- **Unique id**: a PostgreSQL sequence (`va_death_register_number_seq`)
  assigns the human-readable id `<unit_code or site_id>-<6 digits>` when a
  death is registered, or when a direct-mode draft is first started. Gaps
  are accepted. Internally every draft and submission uses a UUID.
- **Drafts** (`va_web_intake_drafts` + `va_web_intake_draft_sections`): the
  package's draft envelope is stored as metadata plus one JSON row per
  questionnaire section. The page sends only the sections whose answers
  changed. Each interviewer edits only their own draft; a death may have
  several (see "Parallel interviews").
- **Prefill contract** (`web_intake_service._prefill_from_death`): the
  package's `createWhoVaInitialDataFromPrefill` (`vendor/who-va-2022/src/
  prefill.ts`) throws if both `deceased.dateOfDeath` and `deceased.
  yearOfDeath` are given, or both `deceased.dateOfBirth` and `deceased.
  ageInYears` — each pair is evidence for the same question, one or the
  other. The server sends `yearOfDeath` only when the exact date is unknown;
  a case prefills only once it has its identity, which includes the exact
  date, so that never happens in practice and only `dateOfDeath` is sent
  (`digitva-dyk`, 2026-09-29). A thrown error previously meant the page silently prefilled
  nothing at all (the caller in `va_intake_form.html` catches it and moves
  on) — the fix is at the source, not the catch.
- **Intake form header** (`digitva-wdj`, 2026-09-29): shows the project and
  site name, or the org unit name with its level (e.g. "PHC Kandaghat") for
  an org-structured project, resolved once per page load by
  `web_intake_service.resolve_draft_display_names()`; the codes stay
  available in a title tooltip. A pinned bar under the header shows the
  deceased's name, date of death, age and sex while filling — seeded from
  the death-register prefill, then refreshed from the answers the host
  already hands `draftStore.save()` on every change (`Id10017`/`Id10018`
  names, `Id10019` sex, the calculated `Id10023` date of death and the
  first finite age of `ageInYears`, `ageInYears2`, `age_adult`,
  `age_child_years` -- `ageInYears` is NaN without a date of birth, which
  used to blank an age-only case's age; `app/static/js/intake/summary.js`,
  `digitva-vzk.1`). Only those four fields; nothing is logged.
- **Which questionnaire a web form carries** (decided 2026-09-19):
  `va_project_master.web_intake_form_type_id`, a form type that must be
  active, carry a `base_instrument_code`, and have a confirmed PII set
  ([New Form Type Onboarding](new-form-type-onboarding.md)). NULL means
  `WHO_2022_VA`, the behaviour before the setting existed. A new web
  `va_forms` row takes the configured type; an existing row keeps the type it
  was created with, so the questionnaire cannot change under drafts already
  being filled.
- **The two project-level extensions** (decided 2026-09-19):
  - `intake_screen` — a welcome note shown before the questionnaire starts.
    `web_intake_intake_note` NULL means the system default text (a module
    constant, `DEFAULT_INTAKE_NOTE`), an empty string means no welcome
    screen. The extension is served exactly when the resolved note is
    non-empty, and the note travels with it in the form-options JSON.
  - `death_summary` — the optional upload of death summary documents, on for
    every project unless an administrator switches
    `web_intake_death_summary_enabled` off. Never a mandatory response.
    Rendering waits for attachments phase 2; the flag and the extension are
    served now.
- **Media (decision W6, 2026-09-19)**: no media is mandatory. Audio narration
  is encouraged, a typed narrative is wanted, and medical papers, discharge
  summaries and prior death certificates are uploaded as available.
  Mandatory-media rules, if they are ever wanted, are project configuration
  added with attachments phase 2.
- **Questionnaire content**: the WHO instrument plus DigitVA's extension
  questions (`abha_number`, `abha_address`, `narr_language`, `imagenarr`,
  `md_count`, `md_im1..30`, `ds_count`, `ds_im1..5`). Context fields
  (`Site`, `unique_id`, `survey_state`, `survey_district`,
  `org_<level>_code`, submitter metadata) are injected by the server at
  submission, never typed by the interviewer.

## Area VA presets

Decided 2026-09-28 (`digitva-dhc`). Two WHO questions are interviewer
instructions about the area, not facts about the individual death, and a
project may want them answered the same way for every interview in a
district rather than asked each time:

- `Id10002` — is this a high HIV/AIDS mortality area?
- `Id10003` — is this a high malaria mortality area?

Both take the WHO choices `high`, `low` or `veryl` (very low). Each may be
set on any node of the project's organization tree
([Organization Model Policy](organization-model.md)), in
`map_org_unit_va_presets` (one row per unit that sets a value; see
`app.models.mas_organization.MapOrgUnitVaPresets`, the precedent is
`map_org_unit_coding_gate`). A unit with no row, or a null field, does not
set that preset — it inherits its nearest ancestor's value, independently
per field, resolved in one ltree query
(`app.services.org_grant_service.resolve_unit_va_presets`).

When a web intake draft is started with an organization unit
(`web_intake_service.start_draft` → `_prefill_from_death`), the resolved
values are merged into `prefill["answers"]` and their question names into
`prefill["lockedQuestionNames"]`, before the death-register answers are
applied — a death-register answer always wins on a key collision, though
today neither preset is ever set from the death register. A unit (and every
ancestor) with no configured value leaves the question asked as normal,
exactly as before this feature existed. Existing drafts are not rewritten
when a preset is added or changed after they were started.

Editable in the Organization admin panel's unit editor ("VA presets"),
`PUT/DELETE /admin/api/organization/<project_id>/units/<org_unit_id>/va-presets`,
same `admin`/`project_pi` permission and audit log entry as the per-unit
coding gate.

`Id10004` (season) stays asked every time (owner decision, not a preset —
season is not a district-level constant the way HIV/malaria prevalence is).
ODK-collected forms are unaffected: this is a web-intake prefill only, never
a form definition change. SmartVA classification keeps using the per-form
`form_smartvahiv`/`form_smartvamalaria` flags
([SmartVA Generation Policy](smartva-generation-policy.md), "Per-Form
Execution Options") — those flags and the resolved area presets can diverge
(e.g. a form flagged `form_smartvahiv=True` in a district whose unit preset
is `low`). Owner decision (2026-09-29): SmartVA's run behaviour stays as
is; its HIV and malaria status comes from the district setting of the
submission's organization unit, falling back to the form-level setting
(`digitva-cts`, [SmartVA Generation Policy](smartva-generation-policy.md)).

## Submission

- The server decides the submission's `interview_outcome` (see "The
  `interview_outcome` question" below; `digitva-vzk.2`, 2026-09-30). A valid
  form (`valid`, with `Id10013` answered) is required only for `completed`;
  `refused` (`Id10013` = no) and the two incomplete outcomes need the minimum
  identity but not a valid form, with one exception (owner, 2026-10-01,
  `digitva-vzk.12`): WHO asks identity after consent, so a direct start
  refused at consent has none. Its submission is stored as `refused` and
  counted as field work, and the nameless case closes as `cancelled`, the only
  closed state the identity constraint allows without an identity. A register
  case already has its identity and goes to `refused` as before. An invalid form with neither refusal nor an
  incomplete outcome is refused (422).
- **Visit note** (owner, 2026-10-01, `digitva-4tb`): the identity-less refusal
  above leaves no record of which household it was, so the form asks a short
  visit note, in that case only: **address** (free text), **visit date** (not
  in the future) and **remarks** (optional). Answer names `visit_address`,
  `visit_date`, `visit_remarks` (`digitva_core`, section `digitva_visit_note`,
  before `interview_outcome`); the form shows the section while consent is no
  and the case identity is incomplete (given name `Id10017`, sex `Id10019` or
  date of death `Id10023` empty), the same condition that keeps a case in
  `draft_identity`. The server requires address and
  visit date on that path (422 otherwise, address at most 500 and remarks at
  most 2000 characters), stores them in the submission payload and as
  `visitNote` in the draft meta, and the nameless case still closes
  `cancelled`. Every other interview is unchanged. No page shows the note to
  supervisors or data managers yet; it is in the stored payload. Server-side re-validation with
  the package's own validator is a planned sidecar (decision W1); until it
  exists the server performs structural checks only.
- Submission is refused while the draft's organization unit is unplaced (no
  parent below the top level; `digitva-8ii`, 2026-09-27), with a 409 asking an
  administrator to map its parent. The picker already hides such units.
- Submission is refused if the draft's organization unit has been deactivated
  or deleted since the draft was started (decision 2026-09-18). Routing only
  attributes a submission to a live unit, so a stale unit would fall back to
  the mapping's unit or leave the case unrouted — and since coding
  eligibility is decided by the routed unit, an unrouted case in a project
  with an organization tree reaches no coder at all. The draft is left
  intact; the interviewer is told which unit and to have it reactivated or
  the case moved before retrying. Failing at submit beats accepting a case
  nobody can ever code. See
  [Organization Model Policy](organization-model.md), "Submission routing".
- The submission is created with the same projection and workflow entry as
  ODK sync (`build_submission_projection`, `ensure_active_payload_version`,
  `route_synced_submission`), so SmartVA, coding and reporting treat it like
  any other case. Identity: `va_sid = web-<draft uuid>-<form id>`. Only a
  `completed` submission enters coding; a refused or incomplete one is routed
  to `consent_refused`, the one existing workflow state that is outside
  coding and blocked from SmartVA (no new workflow state). Data-manager KPIs
  show one "Not analysable" bucket for refused, respondent-unavailable and
  partially completed interviews (and ODK consent = no, as Refused), with a
  count per reason (owner, 2026-10-01, `digitva-4tb`; derived from
  `interview_outcome`, see [Data Manager KPI Framework](kpis.md), C-06).
- The payload carries `intake_source = "web"` and `KEY = web:<draft uuid>`.
- With no attachments the case moves straight to `smartva_pending`, and the
  submit queues SmartVA in the background after commit (a changed revision and
  a supervisor's choice do too; see [Coding Workflow State Machine
  Policy](coding-workflow-state-machine.md), "SmartVA on completion"). A web
  form is on no scheduled SmartVA path, so without this the case would wait
  there.
  Attachment upload (audio narration, document images) is phase 2; until
  then attachment answers are lifted out of the payload and kept on the
  draft as references.
- Every submission writes a `va_submissions_auditlog` row with role
  `vainterviewer`.

## ODK boundary

- Web intake forms are `va_forms` rows with `form_source = 'web'`
  (`odk_form_id = WEB_WHOVA2022`, `odk_project_id = '0'`), one per
  project-site. They are created when an admin sets `web_intake_mode` to a
  value other than `off` (for every active site of the project) and, as a
  fallback, on first use. A project that collects only on the web has no ODK
  mapping, so nothing else would materialize the row that interviewer access
  resolves through.
- ODK sync enumerates `map_project_site_odk` only, so web forms are never
  synced, never retired as missing in ODK, and never written back to ODK.
  `sync_runtime_forms_from_site_mappings()` also excludes `form_source =
  'web'` rows from the forms it rewrites, so an ODK mapping on a project-site
  that also has a web form cannot overwrite the web form's identifiers.
- Editing a submitted web case follows
  [Interview Revisions Policy](interview-revisions.md) (owner, 2026-10-04,
  `digitva-bhpl`). Built on the server (revisions, send-back, reopen, the
  last completed version wins `digitva-xpqm`, supervisor choice
  `digitva-bqzm`); the phone's Revise screen is `digitva-bhpl.2`.

## Ready for web capture

A project can only capture a VA through the browser form when several
settings, spread over five panels, line up. This section is the rule; the
assessment that implements it is
`app/services/web_intake_readiness_service.py`, served as
`GET /admin/api/projects/<project_id>/web-intake-readiness`, shown as the
"Web capture" badge and the "Readiness" list in the Projects panel, and
printed by `flask web-intake readiness <project_id>`.

Each check reports `ok`, `warn` or `fail`. **A project is ready when no check
fails.** A `warn` is something an administrator should look at; it never
stops an interview, so it never makes a project unready.

| Check | What it means | Fails when | Who fixes it, and where |
| --- | --- | --- | --- |
| `mode` | The project collects on the web at all | The project is not active, or `web_intake_mode` is `off` | Administrator, Projects panel |
| `sites` | There is something to collect against | The project has no active project-site; web forms are created per project-site | Administrator or project PI, Project Sites panel |
| `web_forms` | Every active site has its web `va_forms` row | A site has no active `form_source='web'` row; interviewer access resolves through `va_forms`, so a site without one is a site nobody can open the questionnaire for. **Warns** when a row's form type differs from the project's current setting: an existing row deliberately keeps the type it was created with, so the questionnaire cannot change under drafts already being filled | Administrator, Projects panel (re-saving Web Intake materializes the rows) |
| `form_type` | The questionnaire is usable | No form type resolves, the resolved type has no `base_instrument_code` (nothing is bundled to render), or its PII set is unconfirmed (redaction fails closed on every field it owns, so the cases would be unreadable) | Administrator, Projects and Field Mapping panels; [New Form Type Onboarding](new-form-type-onboarding.md) |
| `org_tree` | A submission can route to a live unit | The project has organization levels but a required (non-optional) level has no active unit. Coding eligibility is decided by the routed unit, so such a case reaches no coder. **Warns** when there is no tree at all: routing then falls back to the project-site mapping, which is legitimate | Administrator or project PI, Organization panel |
| `org_unplaced` | Every imported unit has been placed under a parent | Never fails; **warns** while units below the top level have no parent (an import that left them unplaced). The intake picker does not offer them or anything below them until they are placed ([organization-model.md](organization-model.md), "Unplaced units") | Administrator or project PI, Organization panel → Units → Map parents |
| `geography_fields` | The questionnaire itself carries `org_<level_code>_code` per level | Never fails; **warns** when the bundled instrument has no field for a level, or when its field list cannot be read. The web form routes correctly regardless — it fills those codes server-side from the unit the interviewer chose — so this warning is about the same questionnaire collected through ODK Central | Whoever maintains the project's ODK XLSForm |
| `interviewers` | Somebody can fill the form | No active user holds an active interviewer grant reaching the project at project, project-site or organization-unit scope. **Warns** in a project with a tree when every interviewer grant is project- or site-scoped: such an interviewer may name any unit, so nothing narrows what a death is attributed to | Administrator, Access Grants panel |
| `coding_scope` | The collected cases can be coded | `coding_scope_level_id` is set while `coding_intake_mode` is not `pick_and_choose`; random allocation would hand a coder submissions from outside their own units ([Organization Model](organization-model.md)) | Administrator, Projects panel |
| `locales` | Every offered display language exists | Never fails; **warns** when `web_intake_available_locales` names a code the instrument has no translations for. The form drops it silently and opens in English, so a project can be offering fewer languages than it was configured with | Administrator, Projects panel |

The assessment is read-only. It never creates a site, a web form or a grant,
and a project PI may run it only for the projects they manage.

## Case worklist and interview states (baseline 2026-09-29; phases 2 to 7 built 2026-09-30)

Decided by the owner on 2026-09-29 unless a line says otherwise; the
decisions of 2026-09-30 are marked as such. Plan and
phasing: `.tasks/2026-09-28-interviewer-worklist.md` (bead `digitva-vzk`).
This section is a rule baseline; table and column design stays in the plan.
Phases 2 and 3 (the case model, the transition service, direct start creates
the case, the worklist API), phase 4 (the worklist page) and phase 5 (visits,
contact attempts, pause, phones and address) are built; see "Built in phases 2
and 3", "Built in phase 4" and "Built in phase 5" at the end of this section
for the details they fixed. The rest is not built yet, and the
"Baseline" bullets above (own drafts only, one author per draft) hold; a
second interviewer now gets their own copy (see "Parallel interviews").

### The case

- The death register entry is **the case**, for both routes. Register-first
  creates it from the register form; **direct start creates a case
  immediately** with `source = direct` and no identity yet.
- Identity is nullable until set. Minimum identity is **name, date of death
  and sex**; the form's answers (`Id10017`/`Id10018`, `Id10019`, `Id10023`, the
  calculated age) fill it as they are saved. A case cannot leave the pre-
  identity state until all three are present.
- Until then the row shows as "New interview, details pending" and is visible
  to **the interviewer who started it and to supervisors in scope** (owner,
  2026-09-30, item 11). A supervisor sees "details pending, started by
  <name>, <age of the case>", so they can chase or cancel an abandoned start;
  nothing identifying is shown because none exists yet. Teammates do not see it.
- The list is one query over cases; there is one state machine.

### States and transitions

| State | Meaning |
|---|---|
| `registered` | Basics captured, no interview yet |
| `scheduled` | Appointment date set |
| `in_progress` | Form started, answers being saved |
| `paused` | Stopped mid-interview (outcome partially completed) or by choice, with a reason; optional revisit date |
| `not_reachable` | Contact attempt failed, or outcome respondent unavailable; follow-up or revisit date optional |
| `refused` | Respondent declined (outcome refused: `Id10013` = no, or before starting). Soft: never blocks a restart |
| `submitted` | Complete submission accepted; the case enters coding |
| `duplicate` | Same death as another case; links to the kept case |
| `cancelled` | Registered in error |

Allowed transitions: registered ⇄ scheduled → in_progress ⇄ paused →
submitted; in_progress → not_reachable (owner, 2026-09-30); registered /
scheduled / paused / in_progress → not_reachable → scheduled / in_progress;
registered / scheduled / in_progress / paused → refused / duplicate /
cancelled; refused → in_progress (restart, below). `submitted`, `duplicate`
and `cancelled` are terminal except for a **supervisor reopen**. `refused` is
**not** terminal (owner, 2026-09-30): any team member may start or resume a
refused case at any time, which moves it back to `in_progress` and is audited
(who, when). Every reopen records who, when and why.

Owner, 2026-09-30: **no new state for incomplete submissions.** The
submission's `interview_outcome` sets the case state: partially completed ->
`paused`; respondent unavailable -> `not_reachable` (optional revisit date);
refused -> `refused`; completed and first -> `submitted`.

Every transition writes an audit row: **actor, from-state, to-state, reason,
time**. Reasons carry no personal data (UI guidance says so; the field is not
a place for names, phone numbers or addresses).

### Ownership and visibility

- **No assignment.** There is no assign or reassign action and no assignee.
  A case belongs to its registrant until an interview starts, then to the
  interviewer who started it (owner, 2026-09-29).
- **Team cases.** Any interviewer whose scope covers the case may start,
  continue or finish its interview. Every interviewer sees every case in their
  scope. Scope is the existing grant reach (project, project-site or unit
  subtree; see "Role gate vs scope").
- **A signed-in worker gets their whole tree** (owner, 2026-10-04,
  `digitva-yw11`). In a project with an organization tree the unit, not the
  site, is the scope: the unit list a worker gets on sign-in (browser picker
  and device `/units`) is every unit below their granted units, choosable,
  plus the units they report up to, shown as fixed context. Sites are the
  older concept; the device unit list takes no site parameter.
- **Who sees which cases** (owner, 2026-10-03, `digitva-p6fs.24`). The death
  list (registrations and their contacts) is shared by every interviewer of a
  unit. A worker may hold interviewer grants on several units, in one project
  or across projects, and sees the deaths of each granted unit and its
  subtree, each in its own project only. A site-level grant sees every death
  of that project-site, a project-level grant every death of the project.
  When grants overlap on one project-site the wider wins: a site or project
  grant beside a unit grant sees the whole site, while the unit grant alone
  still governs the project's other sites. Interview forms (answers) stay
  their interviewer's own; the case's submission id (`va_sid`) is shown in
  the worklist rows (browser and device) and the single-case detail only to
  the worker whose draft became the submission (see "Parallel interviews"),
  not to whoever first started the case. The supervision list keeps it for
  every case.
- **Own draft per interviewer** (owner, 2026-10-04, `digitva-xz83`),
  replacing the earlier "one shared draft per death" and "only its author may
  edit": each interviewer edits only their own copy. Each save records who
  saved it; the audit trail keeps every interviewer who worked on the case.
  See "Parallel interviews".
- "Mine" is a filter (registered or worked on by me), not a boundary.

### Parallel interviews

**The last completed version wins** (owner, 2026-10-05, `digitva-xpqm`). For
one interviewer's own interview of a case, the coder always gets the
**last completed version, by completion time**: the device's `completedAt`
corrected by `deviceClockAt` (the same drift correction the draft sync uses,
never later than the server's now; the server's now when either time is
missing), or the server's time for a browser submit. Saves and drafts never
compete with a completion: a phone completion is submitted even when a
browser save of the same draft is newer (the browser draft's content is kept
as `replaced` history), and a browser completion made later is then a
correction that wins. This reverses the earlier line of the same day that the
newer version of a draft wins at upload: only completed versions compete.

- A later version of an interview the interviewer already submitted (an upload
  resent with other answers, a second upload of the case under a new
  `client_draft_id`, a browser submit of a draft that is already submitted)
  is a **correction** through the interviewer revision path with the server's
  own reason `resubmitted` (never accepted from a client). It becomes the
  coder's version when its completion time is not older than the stored one's
  (a tie goes to the one received later); an older one is kept as `replaced`
  history, once per set of answers. There is no hash conflict.
- It applies **until coding is final**. A finalised case (a protected workflow
  state with no open send-back or reopen), or a case a supervisor closed
  (`duplicate`, `cancelled`) or a teammate won, no longer takes a version:
  the later one is kept as history and the reply says `locked: true`.
  Send-back and reopen work as in
  [Interview Revisions](interview-revisions.md).
- **The outcome may regress.** If the latest completed version is a refusal
  or partial one, it wins all the same: coding is released, the submission
  routes to `consent_refused`, the case it won leaves `submitted` for that
  outcome's state (`paused`, `refused`, `not_reachable`) and loses its
  `va_sid`, and the case waits for a new complete interview. Teammates'
  superseded copies stay superseded; they are not restored.
- **A second draft of the same interviewer on the case they won** (reachable
  after a regression, a new browser draft, and the first interview completed
  again; `digitva-9kqk`): a browser submit of that draft is a correction of
  the winning submission, not a superseded copy, with the same rules and
  reply as above (`kept`, `locked`, never `superseded: true`; `va_sid` and
  `draft` are the winning interview's). The submitted draft is closed as
  `replaced` with its final answers; the same answers are a payload version,
  or `replaced` history when coding is final or they are older. A teammate's
  draft on the same case is still a superseded copy.
- A correction never tells the case's other draft holders again
  (`case_submitted_by_other` is sent only when a case first becomes
  `submitted`).

Owner, 2026-10-04 (`digitva-xz83`).

- Every interviewer who can see an **open** case (not `submitted`,
  `duplicate` or `cancelled`) gets the case prefill, on the device and in the
  browser, even when another interviewer holds a draft on it.
- Any such interviewer may start their **own copy** (own draft) of the case,
  in the browser or the app. A second start is never refused for another
  interviewer's draft.
- **One draft per interviewer per case.** An interviewer continues from where
  they left off, on the phone or in the browser: the same draft, not a second
  copy. The phone uploads its in-progress draft to the server's draft store at
  sync, and downloads the interviewer's latest server draft when it opens the
  case.
- **Same draft edited in two places** (for example the phone offline and the
  browser): keep both. The most recently saved version becomes the draft. The
  device save time is corrected by the stored clock skew
  ([Field Data Collection Policy](field-data-collection.md), "Interview
  times"); server receipt breaks ties. The other version is kept as history,
  never discarded. The interviewer sees: "This interview was also edited on
  another device; the newer version was kept." There is no section merge.
- **Case identity** (name, date of death, sex) updates only from the
  submitted (winning) draft, not from every save by any draft holder.
- **The submission id** (`va_sid`) is shown to the interviewer whose draft
  became the submission, not to whoever first started the case. This changes
  the `va_sid` rule in "Who sees which cases".
- **Case state stays shared.** One interviewer's contact attempt (for example
  refused) or pause moves the case for everyone. A later submit restarts it.
- Case list rows and the case detail warn that another interviewer has an
  active draft: a boolean and when it started. The other user's name or id is
  never shown. The warning is only as fresh as the phone's last sync, so
  offline, two full interviews of one household can happen. That is the
  accepted cost of this decision.
- The first complete submission wins and moves the case to `submitted` (see
  "One submission per case"). Later uploads and submits of **another**
  interviewer on the case are kept as **superseded copies** on web and device
  alike: answers kept, no submission, no routing. The interviewer is told
  their copy was superseded. A later version by the interviewer whose
  submission won is a correction (above), not a copy.
- **A complete superseded copy is a candidate** (owner, 2026-10-05,
  `digitva-bqzm`). A superseded copy whose `interview_outcome` is `completed`
  (a supervisor's quality reinterview, a teammate's second full interview)
  is a **candidate** for the case's interview. The first interview keeps
  coding meanwhile; nothing changes until a supervisor chooses. An incomplete
  copy, and a `replaced` history row, are never candidates. Case list rows and
  the case detail carry a boolean, `other_complete_interview`, that a second
  complete interview exists: never whose, never its answers.
- **A supervisor, data manager or admin chooses** (the supervisor's choose
  action, see "Supervisors"). The chosen interview becomes the case's
  interview and the other stays a candidate, so the choice can be switched
  back, any number of times.

Built (`digitva-xz83`, part A): `case_prefill` no longer looks at other
drafts; `start_draft` returns the caller's own open draft (a partial unique
index, `uq_va_web_intake_drafts_user_death_open` on `(death_id, user_id)` where
`status = 'draft'`, enforces one per interviewer per case) and never refuses
for another interviewer's; a device upload completes the interviewer's own
open draft on the case when there is one; `save_draft_sections` syncs identity
only for a direct start (`draft_identity`) and `submit_draft` only for the
winning submit; a browser submit on an already closed case stores the draft
as `superseded` (final answers kept in the `final` section, no submission, no
routing, case untouched) and answers 200 `superseded: true`; `va_sid` goes to
the interviewer whose draft became the submission; list rows and case detail
carry `other_draft_active` and `other_draft_started_at`; discarding a draft
returns an `in_progress` case to `registered` only when no other open draft
remains.

Built (`digitva-xz83`, part B): `POST /api/v1/intake/drafts/sync` puts the
phone's in-progress draft into the interviewer's one open draft of the case,
with the conflict rule above (corrected save time, whole-version, loser kept
as a `replaced` draft row, the notice in the reply); a browser save carries
`if_updated_at` and a stale one is refused 409 `draft_stale`; the worklist
shows the other-draft warning. The reply to the final upload is unchanged:
`POST /submissions` with the same `client_draft_id` completes the same draft.
Contract: [Device Collection API](../current-state/device-collection-api.md),
"Draft sync".

Not built (`digitva-xz83`): the Android app's side of the sync (`mobile/`),
and a browser answer the interviewer *clears* after a phone win comes back
from the phone's copy on reload (cleared answers are absent from a browser
section, so the phone's old value is not removed).

### Supervisors

- Medical officers and similar staff at higher-level facilities (PHC, CHC,
  district hospital) over the interviewers in the units below them, plus data
  managers in scope, are supervisors of the cases in their scope.
- A supervisor may **view** the case, **confirm or reject** duplicate and
  cancel flags, and **reopen** terminal cases. A supervisor never assigns.
- **A supervisor chooses between two complete interviews** (owner, 2026-10-05,
  `digitva-bqzm`). On a `submitted` case with a candidate (see "Parallel
  interviews") a supervisor, data manager or admin whose reach covers the case
  may choose the candidate's interview at **any stage**, after final COD
  included (as a reopen). The reason is one of a fixed list, no free text:
  `better_quality`, `more_complete`, `original_incorrect`, `switch_back`.
  The submission keeps its id (`va_sid`); the chosen interview's answers
  become a new payload version (reason `supervisor_choice`), the case's
  identity answers follow it, and `va_data_collector` becomes the chosen
  interviewer. The coder's copy is replaced: coding restarts as for any changed
  payload, the earlier coding and COD are kept as inactive history. The
  previously chosen interview becomes a superseded candidate again (switch
  back). Refused while a reviewer's coding session is live (409). Each choice is
  audited (submission audit row with the reason code, a case transition
  `interview_chosen`), and both interviewers get an `interview_chosen`
  notification. The interviewer whose interview lost can no longer change it:
  a later upload of the same interview is kept as history (`locked`); the
  chosen interviewer's own later versions are corrections as before.
  Supervisors see the candidates' interviewers' names (staff identity, as for
  the registrant and starter); interviewers never do. The supervision list
  filters to cases with a candidate (`candidates=true`).
- **Owner decision, 2026-09-30: a new explicit grant role, `interview_supervisor`,
  with a cadre check.** It works the way `coder` works today: the role is the
  permission, and the cadre is checked when the grant is written. Data managers
  keep supervisor powers through their `data_manager` grant.
- **How a cadre is marked as supervising (item 8).** An admin-set attribute,
  never cadre names in code. It lives on the level x cadre grid row
  (`map_org_level_cadre`) as a third permission, `can_supervise_interviews`,
  next to `can_fill_va_form` and `can_code_va_form`; it is not on the cadre
  itself, so a medical officer can be a supervisor at a PHC or CHC but not at a
  sub-centre. An admin or project PI sets it in the same grid editor and
  workbook import and export (`level_cadres` sheet) as the existing flags.
- **The grant (item 9).** `interview_supervisor` is the permission. Scope:
  **org_unit only** (owner, 2026-09-30, item 16): every supervisor grant is on
  a unit, so every one gets the cadre check; broad supervision is a grant on a
  top unit, which covers everything beneath it, like every unit grant
  (item 10).
- **Write-time check (item 9).** Writing an `interview_supervisor` unit grant
  requires a cadre on the grant, and that cadre must be flagged
  `can_supervise_interviews` on the level x cadre row for the unit's level, the
  same way a `coder` grant requires a cadre with `can_code_va_form`
  ([Organization Model](organization-model.md), cadre rules). The cadre is a
  check made when the grant is written, not itself a permission; after that the
  runtime reads the grant's role. Cadre stays descriptive and is not consulted
  at runtime.
- **Which grants confer supervision.** `interview_supervisor` and
  `data_manager` grants only. `coder` and `interviewer` grants **no longer**
  confer supervision (they did in the first form of this decision, replaced the
  same day). A medical officer who supervises gets an additional
  `interview_supervisor` grant; one grant per user x role x unit already allows
  that alongside their `coder` grant. All other roles (`reviewer`,
  `collaborator`, `collaborator_pii`, `coding_tester`, `site_pi`, `project_pi`)
  confer nothing: explicit authorization, no silent widening. **Decided
  2026-10-02, not built:** in an organizational project the **In-charge** of
  each level (District in-charge: CMO or Civil Surgeon; Block in-charge: SMO,
  CHC; PHC in-charge: MO, PHC) supervises the cases in their own area, and the
  `project_pi` supervises across the whole project (see
  [Access Control Model](access-control-model.md), "In-charge" and
  `project_pi`). Until the In-charge role is built an in-charge supervises
  through an `interview_supervisor` grant, and the `project_pi` confers
  nothing here. Implementation tracked in digitva-0wc.
- **Reach (item 10).** A unit grant covers its unit and everything beneath it,
  as all unit grants do. Confirmed (owner, 2026-09-30, item 17): the
  `interview_supervisor` grant alone gives the supervisor views of that reach,
  with no interviewer grant needed.
- **Privacy rule (item 14).** Supervisors see identifiers (deceased name,
  informant name and phones, address) **only in the worklist and
  case-administration views**. Coding screens keep their existing PII redaction
  (`should_redact_pii`) unchanged: an `interview_supervisor` grant does not lift
  redaction anywhere else.
- **Audit (item 14).** Every supervisor action's audit row names the grant and
  the cadre relied on.
- **Built (digitva-vzk.5, 2026-09-30):** the role, its unit-only `role_scope`
  CHECK and the grid flag (migration `d7f3b1a9c5e2`); the write-time check in
  the admin grants API, the grants panel and the project user import; the one
  predicate `case_transition_service.is_interview_supervisor_for` (unit-grant
  subtree of `interview_supervisor` or `data_manager`, plus `data_manager`
  project and site grants); the supervisor API under
  `/api/v1/intake/supervision/` (list, resolve flag, cancel, reopen). Confirming a duplicate excludes its submission
  from every coding reader through `app/services/duplicate_exclusion.py` and
  revokes any active coding or reviewing allocation (`digitva-vzk.7`; see
  coding-workflow-state-machine.md, "Confirmed Duplicate Cases").
- **Built (digitva-vzk.8, 2026-09-30, migration `a8d4f1c7e3b9`):**
  - **Audit grant and cadre.** Every supervisor action's audit row (resolve
    flag, supervisor cancel, reopen, confirm or mark duplicate, and a flag
    raised by someone who supervises the case) stores
    `authorizing_grant_id` and `authorizing_cadre_id` (the grant's cadre;
    NULL for a data_manager grant, which has none). Team, starter and
    registrant moves leave both NULL. The grant comes from the same
    predicate that decides supervision
    (`case_transition_service.supervising_grant`): the **narrowest** covering
    grant, i.e. the unit grant at the deepest unit, then a data_manager
    project-site grant, then a project grant; at equal depth
    `interview_supervisor` before `data_manager`, then the lowest grant id.
    Confirming an already coded duplicate names the actor's narrowest
    `data_manager` grant, the one that rule relies on.
  - **Supervisor page** `/intake/supervision` (an `interview_supervisor` or
    `data_manager` grant; navbar link "Supervision"): tabs **Flags to
    resolve** and **All cases** (state filter), rows showing who registered
    and who started each case, no informant phone or address (the
    supervision list API drops the masked phones too). Actions: confirm or
    reject a flag, mark duplicate, cancel and reopen, each with a reason
    under the warning "no names, phone numbers or addresses".
  - **Direct duplicate mark** `POST /api/v1/intake/supervision/cases/<id>/duplicate`
    (`duplicate_of`, `reason`): a supervisor without an interviewer grant
    marks a case as a duplicate of another supervised case of the same
    project; both cases outside the caller's supervision read as 404. It is
    confirmed at once unless the data-manager rule holds it as a pending
    flag.
- Authorization stays explicit: project, project-site, form and unit grants
  are not interchangeable, and no supervisory reach is inferred from another
  grant. Supervisor power is bounded by grant scope, grant status and
  closed-project dormancy (the shared `active_project_condition` predicate).

### Duplicate and cancel flags

- **Own registration (owner, 2026-09-30, item 12).** Until an interview has
  started, the person who registered a death may **edit and cancel their own
  registration** without a supervisor; every change is audited (who, when,
  why). Once an interview has started, only the flag-and-confirm route below
  applies.
- Interviewers and supervisors may flag a case as a possible **duplicate**
  (naming the case it duplicates) or for **cancellation** (with a reason).
- An interviewer's flag waits for a supervisor to **confirm or reject**. A
  supervisor's own flag is confirmed at once (owner, 2026-09-29). Every flag,
  confirmation and rejection is audited.
- A confirmed duplicate links to the kept case. Cases are **never merged
  automatically**.
- **Duplicate check.** When a case gains name and date of death (either
  route), other open or submitted cases in the same project are compared:
  date of death within 3 days, same sex, similar normalised name, same or
  neighbouring unit. A match shows "Possible duplicate of <case id>" to the
  interviewer before submit. It is a hint; only a supervisor resolves it. The
  hint shows the case id, never the other case's identity. Rules as built:
  "Built in phase 6" below.

### One submission per case: first complete wins

Owner, 2026-09-29. There is **no lock**. Team members may fill the same case
independently, including offline on their own devices.

- The **first complete submission the server accepts** becomes the case's
  submission. "First" is decided by **server acceptance time**, never device
  time.
- An **incomplete** submission or a **refusal** does **not** close the case
  and does **not** enter coding. It stays with the case until a later complete
  submission supersedes it or a supervisor closes the case. A later complete
  submission from any team member wins; the earlier one is kept as a
  **superseded copy**. This includes a refused case: it blocks nothing, and a
  complete submission moves it to `submitted`, the refusal kept as a
  superseded copy (owner, 2026-09-30).
- After a complete submission has won, every later submission is stored as a
  superseded copy linked to the case. Its interviewer is told; supervisors can
  view it. Submissions are **never merged and never silently dropped**.
- The list shows "Submitted by <name>" on a case a teammate finished, and the
  device copy's submit reports it.

### The `interview_outcome` question

A DigitVA extension question (in `digitva_core`, always on) placed **after
WHO's closing note**, so WHO's own structure is untouched. Values: completed,
partially completed, refused, respondent unavailable.

- Auto-filled `refused` when `Id10013` = no; auto-filled `completed` when the
  form reports every required question answered (`completion.valid`);
  otherwise the interviewer picks partially completed or respondent
  unavailable.
- The case status follows this answer (see "States and transitions").
  **Incomplete** means partially completed or respondent unavailable. This
  answer, not the device or the submit button, drives the first-complete-
  submission rule above.
- **Built** (`digitva-vzk.2`, 2026-09-30). The form engine cannot hold a
  calculated answer that stays editable (a calculation overwrites the answer
  on every change) and cannot express "every required question answered", so
  the question is an ordinary optional choice and **the server sets the stored
  value on submit**: `refused` when `Id10013` = no, `completed` when the form
  is valid (whatever the interviewer picked), otherwise the interviewer's pick,
  which must be partially completed or respondent unavailable. It sits in its
  own always-relevant section (`digitva_outcome`, "Interview outcome"), last
  in the form, not inside WHO's `consented` group, whose relevance would hide
  it after a refusal. Payload field: `interview_outcome`, alongside the other
  DigitVA extension fields. Case audit action: `submitted` for completed,
  `submitted_<outcome>` otherwise. The case's `va_sid` is set only by a
  completed submission; a refused or incomplete one stays linked through its
  draft.
- **ODK side.** The ODK form has no `interview_outcome`; ODK-synced
  submissions are routed as before (consent alone decides). A project that
  also collects on ODK may add a `select_one` named `interview_outcome` with
  the same four values at the end of its form; nothing reads it from ODK
  payloads today.
- Labels are English in the instrument. The other twelve locales' layer
  strings were seeded by migration; `interview_outcome` has none yet, so it
  falls back to English until a translation is added in the admin string
  editor or a seed migration.

#### Incomplete submissions (owner, 2026-09-30)

- A valid form (`completion.valid`) is required **only** for outcome
  `completed`. The other outcomes need the `interview_outcome` answer and the
  minimum identity (name, date of death, sex). They do **not** need the
  consent answer (`Id10013`), which a respondent-unavailable interview may
  never reach.
- **Stop interview** stays as the interviewer's way to record the two
  incomplete outcomes, with an optional revisit date. Not yet built as a
  submit: the web form submits only a valid questionnaire, so today an
  incomplete submission reaches the server only through the API; the
  worklist's pause and visit date remain the web path.
- An incomplete or refused submission still does not enter coding.

#### Restarting a refused case (owner, 2026-09-30)

Refused is fully soft. A refusal never blocks another attempt: any team member
in scope may start or resume it, and a complete submission wins. The earlier
owner decision that a supervisor may reopen a refused case (2026-09-29) is
**superseded**: it has no function, because no reopen is needed. History line
kept for the record. Nothing further is required of the restarter (owner,
2026-09-30, item 13): no reason, no warning; the audit row records who
restarted it and when.

#### Duplicate on a submitted case (owner, 2026-09-30)

A supervisor may confirm a **submitted** case as a duplicate of a kept case.
The supervisor chooses the kept case; the UI warns when the case marked
duplicate is the one already coded.

**Mechanism (owner, 2026-09-30): case-level exclusion, not a coding-state
change.** Confirming marks the case as a confirmed duplicate, pointing at the
kept case. The submission's coding workflow state is left exactly as it was:
no new state, no new transition, and `not_codeable_by_data_manager` is **not**
reused (it is legal only from `screening_pending`, `smartva_pending` and
`ready_for_coding`, has no clearing path, and is a data-manager-owned record).

- **One shared predicate.** Everything that reads coding state excludes
  submissions whose case is a confirmed duplicate through a single shared
  predicate, the same pattern as the closed-project `active_project_condition`
  ([Access Control Model](access-control-model.md)); never per-call-site ad hoc
  filters. Readers covered: coder allocation, the pick-and-choose list, queue
  and dashboard counts, SmartVA generation, reviewer and secondary coding
  queues, exports, and analytics and materialized views.
- **Being coded now:** the active allocation is revoked when the duplicate is
  confirmed (the existing allocation-timeout mechanism, [Coding Allocation
  Timeouts](coding-allocation-timeouts.md)).
- **Undo** clears the mark; the submission continues from the state it was in.
- **Already finalized:** the stored coding stays intact, the case is excluded
  from reporting counts, and nothing is un-finalized or deleted. Only a
  supervisor **holding a `data_manager` grant** may confirm it.
- Confirmation and undo are audited.
- **Build requirement:** a test that enumerates every allocation, list, count,
  export and view path and fails when one ignores the predicate.
- **Doc follow-up when built:** [Coding Workflow State
  Machine](coding-workflow-state-machine.md) needs one sentence saying case-
  level exclusion is not a workflow state. It is not edited now.

- Being a new extension question it is subject to the PII-registry rule in
  [Field Data Collection Policy](field-data-collection.md) if it ever carries
  personal data; as a choice it does not.

### Contact data and attempts

- Keep the informant name and phone. Add an optional second phone and a
  structured address (house or street, village or ward, landmark) beside the
  org unit.
- Phones are validated (Indian mobile format) and **masked in lists**; shown in
  full only on the case page.
- **Single-case detail** (owner, 2026-10-03, `digitva-p6fs.24`). One case's
  detail (`GET /api/v1/intake/cases/<death_id>`, one route for the browser and
  the native app) shows the full contact
  details: informant name, both full phones, the household address fields and
  the remarks. Lists (the worklist, which the device lists per project, and
  supervision) stay masked. The detail is one body for every client, and the
  reply of every single-case action; it carries the case's links and, only
  when the caller may start or resume the interview (they hold its active
  draft, or the case is open and no other interviewer's draft holds it), its
  prefill for offline interviews, which includes ABHA and the parents' names.
  For a case another interviewer started or one already submitted, duplicate
  or cancelled, the `prefill` key is absent. The detail's own fields never
  carry ABHA, the parents' names, other users' ids or client ids, and it is
  answered `Cache-Control: no-store`.
  Its visibility is exactly the worklist's (team cases in scope, see "Who
  sees which cases"; "details pending" for its starter only), in any state; a
  case outside it, or an unknown id, is 404. `va_sid` is null unless the
  caller started the case. The native app may keep the
  detail of an active case offline under
  [Field Data Collection](field-data-collection.md) ("Offline contact
  details"); the browser keeps nothing.
- **Projects on a native device** (owner, 2026-10-03). A native device may
  work in every project the worker is an interviewer in, naming the project
  on each project-scoped call (no default project); the browser
  (PWA included) keeps server-side project access only, with no
  multi-project persistence or offline storage.
- **Contact attempts** record the outcome only (reached, no answer, wrong
  number, moved, refused), the next date and the user. No free-text notes:
  they would carry personal data.

### Prefill map

Prefill applies once, when a draft is created and has no saved answers.
Unlocked prefills are ordinary answers the interviewer may change; edits to
name, sex and date of death flow back to the case (the form is the record of
the interview). `org_<level>_code` stays server-injected at submission.

Built 2026-09-30 (`digitva-vzk.1`, `digitva-vzk.3`) in
`web_intake_service._prefill_from_death`:

| WHO question | Source | Locked |
|---|---|---|
| `Id10010` / `Id10010c` interviewer name and id | signed-in user (`digitva-dyk`) | yes; `Id10010` only when the name meets its letters-and-spaces constraint, else editable |
| `Id10002` / `Id10003` HIV / malaria area | district presets (`digitva-dhc`, done) | yes |
| `Id10017` / `Id10018` given name, surname; `Id10019` sex | case | no |
| `Id10021` date of birth | case `date_of_birth` (sends no age: the form calculates it) | no |
| `age_group` and its age field | case `age_years` when there is no exact date of birth: 12-119 as adult (`age_adult`), 1-11 as child in years (`age_child_unit` = years, `age_child_years`); 0 is not prefilled (days or months cannot be told) | yes (`digitva-q219`): `age_group` with `age_adult`, or with `age_child_unit` and `age_child_years`; nothing age-related when the case has no prefilled age |
| `Id10022` = yes, `Id10023_a` (with a date of birth) or `Id10023_b` date of death | case | no |
| `Id10058` where the deceased died | case `place_of_death`, mapped to WHO choices (see below) | no |
| `Id10057` where the death occurred (country, state, district, village) | org path names of the case's unit, root first, then "; " and the case address | no |
| `Id10055` usual residence | case address, else the same org path | no |
| `Id10051` = yes | set whenever `Id10055` or `Id10057` is (they are asked only then) | no |
| `Id10007` respondent name | case informant name | no |
| `Id10061` / `Id10062` father's / mother's name | optional registration-form fields `father_name` / `mother_name` (`digitva-vzk.1`) | no |
| `Id10010b` interviewer sex | user-profile `sex` (`digitva-vzk.3`) | yes, when the profile has a sex |
| `abha_number` / `abha_address` | case | yes (unchanged) |
| `Id10020` = no, `dob_precision`, `dob_month_year` / `dob_year` | case `date_of_birth_partial` when there is no exact date: `YYYY-MM` gives `month_year` and `dob_month_year` = YYYY-MM-01; `YYYY` gives `year` and `dob_year` = YYYY-01-01 (the ODK date storage for those appearances). `Id10021` stays empty. Age still prefills (and locks) beside it (`digitva-tld2`) | no |

`Id10010a` interviewer age is not prefilled or locked (owner decision
2026-10-03, `digitva-q219`); the interviewer answers it.

Rules as built:

- **Locked prefill is enforced on the server** (`digitva-p6fs.9`). The
  locked set and values are recomputed by the server from the case and the
  draft's owner at each save and submit (`_draft_locked_answers`), never
  read from the stored prefill, so a corrected registration wins; the client's
  `lockedQuestionNames` only drives the read-only display and is never
  read back. On every draft save, a locked answer a section carries, or
  carried in its last save, is set to its authoritative value; on submit
  (and for a device superseded copy) every locked answer is set, added if
  the client left it out, before relevance is derived. The server
  **overwrites rather than refuses**: an offline device interview may hold
  a stale locked value (a profile edit, an age crossing a year), and a
  refusal would strand a completed interview the interviewer cannot fix.
  A draft saved before a lock existed (no `lockedQuestionNames`, `{}`, or
  an older list) therefore gets today's locks; the stored row is not
  rewritten. An exact date of birth captured in the interview wins over the
  registered age (owner decision 2026-10-03): the interview talks to the
  family, so its date is the better record. `age_group` is asked only when
  `Id10020` or `Id10022` is not yes, so the locked age is then irrelevant and
  dropped at submission, and the age comes from that date.
  Unlocked answers keep their saved-answer semantics (an unchanged answer
  stays, a cleared one is cleared).
- **Name split**: the first word of the case name is the given name
  (`Id10017`), the rest the surname (`Id10018`); a one-word name has no
  surname. Owner decision open: last word as surname suits Indian names
  better ("Ram Kumar Sharma" gives "Ram" / "Kumar Sharma" today).
- **Case address**: house or street, village or ward, landmark, then the
  free-text address, comma-joined.
- **`Id10058`**: the register's place of death is free text (the form offers
  the WHO labels as suggestions). A WHO value or English label maps exactly;
  otherwise keywords, in order: on route (route, on the way, transit,
  ambulance), other health facility (PHC, CHC, health centre, sub centre,
  clinic, dispensary, nursing home, facility), hospital, home (home, house,
  residence). No match leaves the question unanswered; never `other` by
  default.
- **Direct start**: no case fields yet, so only the interviewer, presets,
  and `Id10057` / `Id10055` from the org path.
- Only name, sex and date of death flow back to the case; parents' names,
  place and respondent do not.
- `Id10061` / `Id10062` are asked for children and neonates only; an adult's
  prefilled parents' names are dropped as irrelevant at submission.
- Year of birth and sex are optional, set in Profile or by an admin (the
  admin master list shows them; the user search a project PI calls does
  not), and never logged; year of birth no longer prefills anything. `Id10010a` / `Id10010b` are registered PII fields
  (`app/services/pii_field_registry.py`).

### The list

- Default view: **team cases** in my scope with a **Mine** filter and a state
  filter, sorted by next visit date, then last activity.
- Tabs: **To visit** (registered, scheduled, not reachable, paused), **In
  progress**, **Done** (submitted, refused).
- Row: id, name (or "details pending"), sex, age, date of death, unit, state
  badge, next visit date, primary action (Start, Resume, Log attempt).
- Page top: **Register death** and **Start new interview**, shown as the
  project's `web_intake_mode` allows (`death_register`: register only;
  `direct`: start only; `both`: both; `off`: neither).
- Supervisors get an **All in my scope** view showing who registered and who
  started each case (built: `/intake/supervision`, see "Supervisors"). There
  is no reassignment.

### Offline capture

Owner, 2026-09-29: offline capture is in scope for this feature. Owner,
2026-09-30: **offline capture runs in the native app only, under Path B of
[Field Data Collection Policy](field-data-collection.md) exactly as written.**
The browser page stays online-only (Path A, unchanged): no PWA, no
browser-stored drafts, and no amendment to that policy.

- Device drafts follow Path B: encrypted at rest, hardware-backed keys, one
  store per interviewer behind a PIN unlock gate, purged only after the server
  acknowledges the upload, wiped on logout and on revocation for that
  interviewer's store only, and no retention ceiling on unsent work (decision
  C3, accepted risk recorded there). This baseline's earlier word "bounded" is
  dropped in favour of C3.
- A case registered offline gets a **client-generated id** the server
  reconciles. **Duplicate checks run on upload.**
- The list shows "Submitted by <name>" when a teammate finished a case while
  the device was offline, and the offline copy's submit says so.
- **A device draft that arrives after a teammate's complete submission won**
  (owner, 2026-09-30, item 6) is uploaded **automatically as a superseded
  copy**, linked to the case and visible to supervisors; the interviewer is
  told that a teammate already completed the case and their copy was saved as
  a backup. Nothing is lost and nothing waits on the device.
- **A device copy is that interviewer's own attempt** (owner, 2026-09-30,
  item 18). It reaches the server as its own submission under
  first-complete-wins and is **never merged** into the team's shared server
  draft.

### Phasing

Plan phases: 1 prefill and death-list fixes; 2 case model and transition
service; 3 direct start creates the case and one worklist API; 4 worklist UI;
5 appointments, contact attempts, pause, and the register form's structured
address and validated phone; 6 duplicate check
and supervisor resolution; 7 supervisor view. Offline capture is in no phase of
this plan: it is native-app work under Path B. This baseline precedes phase 2.

### Decided 2026-09-30

Recorded above; removed from the open list.

- Former item 1, supervisor role model: a new explicit `interview_supervisor`
  grant role with a write-time cadre check ("Supervisors"); the same-day first
  form (derive from the cadre, carried by `coder` and `interviewer` grants) was
  replaced. Its follow-ups (items 8 to 10 and 14) are decided below.
- Former item 8, state after an incomplete or refused submission: no new
  state; the outcome sets it, and refused is soft ("States and transitions").
- Former item 9, existing submit rule: replaced ("Incomplete submissions",
  "Submission").
- Former item 10, duplicate from `submitted`: allowed, coding follows state
  ("Duplicate on a submitted case").
- Owner decision 5 of 2026-09-29 (supervisor may reopen a refused case) is
  superseded by soft refusal.
- Item 8, how a cadre is marked as supervising: an admin-set flag on the level
  x cadre grid ("Supervisors").
- Item 9, which grants carry the power: a new explicit `interview_supervisor`
  grant role with a write-time cadre check (the cadre must be flagged
  `can_supervise_interviews` at the unit's level), plus `data_manager` grants.
  `coder` and `interviewer` grants confer nothing ("Supervisors").
- Items 10 and 14, reach, identifier visibility and audit: see "Supervisors".
  Item 10 (subtree) is resolved on the basis that a unit grant covers its unit
  and everything beneath it.
- Items 11, 12, 13 and 17 (owner, 2026-09-30): "details pending" is visible to
  its starter and to supervisors; a registrant may edit and cancel their own
  registration until an interview starts, audited; a refused case restarts
  with no notice or reason, audit only; the supervisor grant alone gives the
  supervisor views.
- Item 16, scope of the `interview_supervisor` grant: unit scope only, so the
  cadre check applies to every supervisor grant (no project- or site-scoped
  supervisor grants). The `role_scope` constraint for the new role therefore
  allows `org_unit` only.
- Item 15, mechanism for a confirmed duplicate: case-level exclusion, see
  "Duplicate on a submitted case".

- Former items 2, 3, 4, 5 and 7 (owner, 2026-09-30), offline: all answered by
  Path B ("Offline capture"). Item 7: offline runs in the **native app only**;
  the browser page stays online-only and Path A is not amended. Item 2, keys:
  hardware-backed storage, one store per interviewer, PIN unlock gate. Item 3,
  storage bounds: **no retention ceiling** on unsent work (decision C3); the
  baseline's earlier "bounded" is dropped. Item 4, expiry: none, a consequence
  of C3; the server-side outstanding-work report is the control. Item 5, wipe:
  on logout and on revocation, for that interviewer's store only.

### Built in phases 2 and 3 (digitva-vzk.4, 2026-09-30)

Details the baseline left open, fixed by the implementation
(`app/services/case_transition_service.py`, migration `c4e8a2f6b9d3`):

- **The pre-identity state is `draft_identity`.** Sex is nullable too, not
  only name and date of death, because a direct start has none of the three
  (decision 4). A database CHECK requires all three outside `draft_identity`
  and `cancelled`. Identity comes from `Id10017`/`Id10018` (name), `Id10019`
  (sex: `male`, `female`, `undetermined`) and `Id10023` (else `Id10023_a` or
  `Id10023_b`, following its calculation); an empty or invalid answer never
  blanks what the case holds.
- **Three transitions the table did not list:** `draft_identity ->
  in_progress` when the form captures the identity (by its starter);
  `draft_identity -> cancelled` when the starter discards a draft that never
  had an identity; `in_progress -> registered` when a draft is discarded (the
  existing discard behaviour). A direct start discarded after its identity was
  captured goes to `registered` and stays a team case, rather than being
  cancelled.
- **Who may make each move** is a column of the transition table: any team
  member in scope; the starter; the registrant (`registered`/`scheduled` ->
  `cancelled`, decision 12 of 2026-09-30); or a supervisor (`-> duplicate`,
  `in_progress`/`paused` -> `cancelled`, confirming or rejecting a flag,
  reopen). Supervisor moves ask one predicate,
  `is_interview_supervisor_for`, which **fails closed** until the
  `interview_supervisor` role exists (`digitva-vzk.5`). A reopen returns the
  case to the state recorded before it became terminal.
- **Flags:** a case carries at most one pending flag (`duplicate` naming the
  kept case in the same project, or `cancel` with a reason);
  `POST /api/v1/intake/cases/<death_id>/flags`.
- **Submission rule unchanged** (valid form and `Id10013`) until the
  `interview_outcome` question is built (built: `digitva-vzk.2`); a submission moves its case to
  `submitted`. A direct start whose answers lack the minimum identity is
  refused at submit (422).
- **Lists:** `GET /api/v1/intake/deaths` stays the death register
  (`source = register` only) and still accepts the old status names
  `va_in_progress` and `va_submitted` as filters. The worklist is
  `GET /api/v1/intake/cases` (`mine`, `state`, `limit` up to 200, `cursor`), sorted
  by last activity until phase 5 adds visit dates (superseded: see "Built in
  phase 5"); its rows carry no informant name, phone or address. Since
  `digitva-p6fs.24` it is answered `Cache-Control: no-store`, and takes an
  optional `project_id` to restrict it to one project.

### Built in phase 4 (digitva-vzk.6, 2026-09-30)

The worklist page (`/intake/`, `app/templates/va_frontpages/va_intake.html`,
`app/static/js/intake/intake_worklist.js`) replaces the "My drafts" and
"Registered deaths" lists. No schema change.

- **One list** over `GET /api/v1/intake/cases`: team cases by default, a **Mine
  only** switch, tabs **To visit** (registered, scheduled, not reachable,
  paused), **In progress** (in progress, details pending) and **Done**
  (submitted, refused; duplicate and cancelled shown as **Closed**). Tab counts
  come from the API's `counts`. Keyset **Load more** follows `next_cursor`.
  The list spans every project-site of the caller's interviewer grants; the
  project/site and unit pickers only steer **Register death** and **Start new
  interview**, which show as `web_intake_mode` allows.
- **Row:** case id, name (or "New interview" with a "Details pending" badge),
  sex, age, date of death (a plain date, never shifted), unit, state badge,
  last activity in the user's timezone, and a pending-flag badge.
- **Primary action:** **Resume** opens the caller's own draft; otherwise
  **Start** (registered, scheduled, paused, not reachable), **Restart**
  (refused) or **Resume** (in progress, details pending) calls
  `POST /api/v1/intake/drafts` with the case. A second interviewer on a case
  with someone else's draft starts their own copy; the row warns with
  `other_draft_active` (see "Parallel interviews").
- **Secondary actions:** **Flag duplicate** (the kept case picked from cases in
  scope of the same project, the 200 most recently active) and **Flag for
  cancel** (reason required, 200 characters), both with the warning "No
  names, phone numbers or addresses in the reason". Hidden while a flag is
  pending.
- **Browser storage:** only the chosen project/site, unit, tab and Mine switch;
  no case data in storage or URLs (Path A).
- **Not in phase 4:** the next visit date and **Log attempt** (phase 5, with
  appointments), and the register form's structured address and validated
  phone, moved to phase 5 so it ships with that phase's migration.

### Built in phase 5 (digitva-vzk.9, 2026-09-30)

Migration `e5b2c8d4a1f7`; `app/services/web_intake_service.py` (`set_visit`,
`log_contact_attempt`, `pause_interview`); every state change goes through
`case_transition_service.transition()` and writes its audit row.

- **Case columns:** `next_visit_at` (appointment or follow-up) and
  `last_contact_at`; `informant_phone_2`; structured address
  `address_house_street`, `address_village_ward`, `address_landmark` (200
  characters each) beside the free-text `address`.
- **Phones:** both phones must be an Indian mobile number: 10 digits starting
  6-9, with an optional `+91` or `0` in front; spaces and hyphens are ignored.
  Stored as the 10 digits. Checked on register (there is no edit endpoint
  yet). Worklist rows carry only `informant_phone_masked` /
  `informant_phone_2_masked` (`******1234`); `serialize_death` (the register
  response) keeps the full numbers. Older free-text phones are masked to their
  last four digits.
- **Visit dates** are ISO date-times with a timezone (the page sends the
  browser's local time as UTC), from yesterday to a year ahead.
- **Set visit** (`POST /api/v1/intake/cases/<death_id>/visit`, body
  `next_visit_at` or `null`) on a case waiting for a visit (registered,
  scheduled, not reachable, paused): a date moves registered and not reachable
  to `scheduled` (audit `visit_scheduled`) and only changes the date on
  scheduled or paused; `null` moves scheduled back to `registered` (audit
  `visit_cleared`) and only clears the date elsewhere. A date-only change
  writes no audit row.
- **Log attempt** (`POST /api/v1/intake/cases/<death_id>/attempts`, body
  `outcome`, optional `next_visit_at`) on the same states writes one
  `map_case_contact_attempts` row (outcome, time, next date, user; no notes)
  and sets `last_contact_at`:
  - `refused` -> `refused`, visit date cleared; a next date is refused (400).
    This includes a family first logged as not reachable
    (`not_reachable -> refused`, team, added 2026-09-30).
  - `no_answer`, `wrong_number`, `moved` -> `not_reachable` (stays so if
    already), next visit = the given date or none.
  - `reached` -> with a date, registered and not reachable become `scheduled`
    and a scheduled or paused case takes the date; without one, no state or
    date change. Chosen so a reached family without a date keeps its
    appointment, and because `paused -> scheduled` is not a transition.
  Audit actions are `contact_<outcome>` when the state changes.
- **Pause** (`POST /api/v1/intake/cases/<death_id>/pause`, body `reason`,
  optional `next_visit_at`): `in_progress -> paused`; the reason is a code
  (`respondent_busy`, `respondent_left`, `needs_other_respondent`, `other`),
  never free text. **Resume** is the existing start: `POST /api/v1/intake/drafts`
  with the case moves `paused -> in_progress`. Starting or resuming an
  interview clears `next_visit_at`.
- **Scope and CSRF:** the three POSTs resolve the case through `get_death`
  (out of scope reads as 404) and are CSRF-checked (`X-CSRFToken`). Their
  response is the case's id, state and dates only.
- **Worklist order:** next visit ascending (overdue first), cases without a
  date last, then last activity newest first; keyset-paged on
  (`next_visit_at`, `updated_at`, `death_id`), index
  `ix_va_death_register_next_visit`. The cursor format changed; an old cursor
  is refused (400). **Mine** also counts cases the user logged an attempt on.
- **Page:** rows show the next visit, last contact and the masked phone.
  **Log attempt** is the primary action on a not-reachable case (Start stays
  beside it); **Set visit** and **Log attempt** show on every case waiting for
  a visit; **Pause** on an interview in progress; a paused case's start reads
  **Resume**. Inline forms, no modal; nothing kept in browser storage. The
  register form gains the structured address, a second phone and the phone
  format hint (checked by the browser and again by the server).
- **PII registry:** not applicable. The new columns stay on the case and
  never enter the submission payload (`build_web_payload` copies only the ABHA
  fields and the case id) or an export.

### Built in phase 6 (digitva-vzk.11, 2026-09-30)

No migration. `app/services/web_intake_service.py`
(`_possible_duplicate_rows`, `possible_duplicates`); computed on read, never
stored, so a case gets the check whichever route (web, device upload) gave it
its name and date of death.

- **Match:** another case of the same project, not the case itself, not
  `cancelled` and not a confirmed `duplicate` (neither can be named as the
  kept case), with a name and a date of death, where
  - the dates of death are at most 3 days apart (inclusive);
  - the sex is the same, or either is missing, `unknown` or `undetermined`;
  - the normalised names have a pg_trgm `similarity()` of at least 0.5.
    Normalised: lowercase, punctuation to spaces, the titles late, lt, mr,
    mrs, ms, miss, smt, shrimati, shri, sri, dr, master, baby, kumari and km
    dropped as whole words, spaces collapsed;
  - the units are neighbours: the same unit, the parent, a child, or a
    sibling (same parent), or either case has no unit. A grandparent or
    cousin is not a neighbour, nor are two top-level units.
  The case being checked must itself have a name and a date of death, not be
  closed and carry no pending flag (it is already with a supervisor);
  otherwise it gets no hint.
- **Scope:** candidates are limited to the caller's worklist reach
  (`_worklist_scope`), so the hint never names a case the caller cannot open;
  a match outside it is not shown to that caller.
- **Case API:** `GET /api/v1/intake/cases/<death_id>/possible-duplicates`
  (interviewer; the case through `get_death`, out of scope reads as 404):
  up to 50, most similar first, each with `death_id`, `unique_id`,
  `unit_name`, `state` and `score`. No name, sex, date, phone or address.
- **Form page:** checked on open, after a save that touched the identity
  answers (`Id10017`, `Id10018`, `Id10019`, `Id10023`, `Id10023_a`,
  `Id10023_b`) and just before submit. A warning banner "Possible duplicate
  of <ID>" with a **Flag as duplicate of <ID>** button per case (the existing
  flag endpoint; a supervisor confirms or rejects). It never blocks submit and
  nothing is merged.
- **Worklist:** each row carries `possible_duplicates` (up to three
  `death_id`/`unique_id` pairs) from ONE query for the whole page; the row
  shows a "Possible duplicate of <ID>" badge unless a flag is already
  pending, and **Flag duplicate** offers those cases first, preselected.
- **Index:** the candidate side filters on project and a date window; the
  existing `ix_va_death_register_project_status` serves the project. For large
  registers, `(project_id, date_of_death)` is the index to add (not added in
  this phase).

### Open design items (questions for the owner)

- **Date of death unknown** (found building phase 3). A direct start whose
  respondent knows only the year of death (`Id10022` = no, `Id10024`) never
  gets a date of death, so it cannot leave `draft_identity` and cannot be
  submitted. Should the minimum identity accept a year of death, and how
  should the case store it?

## Self-coding projects

Owner decision 2026-10-05, `digitva-xuxk`. In a self-coding project the
medical officer interviews and then codes their own case.

- **Project setting** `va_project_master.self_coding_enabled`, off by
  default. It can be on only while the project's `web_intake_mode` is not
  `off`: turning it on in a project with intake `off` is refused.
- **Coder implies interviewer.** In a self-coding project a `coder` grant also
  lets its holder interview, at the same scope as the `coder` grant. This is
  derived when grants are read; no `interviewer` grant row is written, and the
  grant lists do not show one. Turning the setting off, or revoking the
  `coder` grant, removes it. It exists only while the intake mode is not
  `off`, since an `off` project has no interviewing.
- **Mentoring institute members are excluded.** Their `coder` grant does not
  imply interviewing: they may not interview (see [Roles
  Explained](roles-explained.md), "Medical college mentors").
- **Code this case now.** After a completed interview with valid consent, the
  submit reply, in the browser and in the app, offers "Code this case now".
  What it does, and when it is refused, is in [Coding Workflow State Machine
  Policy](coding-workflow-state-machine.md), "Self-coding". The interviewer
  worklist shows "Code now" on the user's own completed interviews that still
  await coding.
- Nothing else changes: the case reaches coding by the normal path, and
  review, recode, revisions and send-back follow their own rules.

See [Access Control Model](access-control-model.md), "Implied roles".

## Not yet implemented

- Attachments (phase 2), the validator sidecar (W1), offline mode, native
  app. Of "Case worklist and interview states" above, the case state machine,
  flags and the worklist API (phases 2 and 3), the worklist page (phase 4) and
  visits, contact attempts and pause (phase 5) and the possible-duplicate
  check (phase 6) are built; team drafts,
  supervisor powers and views, the `interview_outcome` question and its
  first-complete-submission rule are built; team drafts, telling the
  interviewer of a superseded copy, a web "Stop interview" submit and offline
  capture are **not implemented**. The server side of a device upload,
  including storing a late device interview as a superseded copy, is built
  (`digitva-kmk.1`, [Device Collection API](../current-state/device-collection-api.md)). Offline capture is native-app work under Path B of
  [Field Data Collection Policy](field-data-collection.md) (no amendment
  needed), not a web-page feature; it has open design items 6 and 18 there.
  ("Unit-scoped listing refinements" was struck on 2026-09-19: there was
  no concrete item behind it, and `list_deaths` already scopes by unit
  grants.)

Web intake is path A of
[Field Data Collection Policy](field-data-collection.md), which fixes the rule
this path follows and keeps: answers are never persisted in the browser.
Offline capture is not a web-intake feature; it is the native app's Path B,
which sets the conditions an offline collector must meet before it may hold
interview data on a device.
