---
title: Web Intake Policy (WHO VA 2022 questionnaire in DigitVA)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-30
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
- **Unique id**: a PostgreSQL sequence (`va_death_register_number_seq`)
  assigns the human-readable id `<unit_code or site_id>-<6 digits>` when a
  death is registered, or when a direct-mode draft is first started. Gaps
  are accepted. Internally every draft and submission uses a UUID.
- **Drafts** (`va_web_intake_drafts` + `va_web_intake_draft_sections`): the
  package's draft envelope is stored as metadata plus one JSON row per
  questionnaire section. The page sends only the sections whose answers
  changed. One active draft per registered death; only its author may edit
  it.
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
  names, `Id10019` sex, the calculated `Id10023` date of death and
  `ageInYears`). Only those four fields; nothing is logged.
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

- A draft is submitted only when the questionnaire reports `valid` and the
  consent question (`Id10013`) is answered. **Replaced when the worklist
  phases land** (owner, 2026-09-30; see "Incomplete submissions" below): a
  valid form is then required only for the `completed` outcome, and the other
  outcomes need the `interview_outcome` answer and the minimum identity but
  not `Id10013`. Until then this rule is the running behaviour. Server-side re-validation with
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
  any other case. Identity: `va_sid = web-<draft uuid>-<form id>`.
- The payload carries `intake_source = "web"` and `KEY = web:<draft uuid>`.
- With no attachments the case moves straight to `smartva_pending`.
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
- Editing a submitted web case is not supported in this phase.

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

## Case worklist and interview states (baseline 2026-09-29; phases 2 and 3 built 2026-09-30)

Decided by the owner on 2026-09-29 unless a line says otherwise; the
decisions of 2026-09-30 are marked as such. Plan and
phasing: `.tasks/2026-09-28-interviewer-worklist.md` (bead `digitva-vzk`).
This section is a rule baseline; table and column design stays in the plan.
Phases 2 and 3 (the case model, the transition service, direct start creates
the case, the worklist API) are built; see "Built in phases 2 and 3" at the end
of this section for the details they fixed. The rest is not built yet, and the
"Baseline" bullets above (own drafts only, one author per draft, 409 for a
second interviewer) remain the running behaviour until team drafts land.

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
- **One shared draft per death**, replacing "only its author may edit". Each
  save records who saved it; the audit trail keeps every interviewer who
  worked on the case.
- "Mine" is a filter (registered or worked on by me), not a boundary.

### Supervisors

- Medical officers and similar staff at higher-level facilities (PHC, CHC,
  district hospital) over the interviewers in the units below them, plus data
  managers in scope, are supervisors of the cases in their scope.
- A supervisor may **view** the case, **confirm or reject** duplicate and
  cancel flags, and **reopen** terminal cases. A supervisor never assigns.
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
  confer nothing: explicit authorization, no silent widening.
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
- **Docs to amend when built** (not edited now; they stand until then): Access
  Control Model, Role To Scope Rules and the `role_scope` check constraint (a
  migration) gain the new role; the grants panel and grant import gain the
  option; Organization Model gains one sentence that `interview_supervisor`
  joins `coder` as a role whose grant needs a cadre check. Coding Workflow
  State Machine is amended as noted under "Duplicate on a submitted case".
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
  hint shows the case id, never the other case's identity.

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

#### Incomplete submissions (owner, 2026-09-30)

- A valid form (`completion.valid`) is required **only** for outcome
  `completed`. The other outcomes need the `interview_outcome` answer and the
  minimum identity (name, date of death, sex). They do **not** need the
  consent answer (`Id10013`), which a respondent-unavailable interview may
  never reach.
- **Stop interview** stays as the interviewer's way to record the two
  incomplete outcomes, with an optional revisit date.
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
- **Contact attempts** record the outcome only (reached, no answer, wrong
  number, moved, refused), the next date and the user. No free-text notes:
  they would carry personal data.

### Prefill map

Prefill applies once, when a draft is created and has no saved answers.
Unlocked prefills are ordinary answers the interviewer may change; edits to
name, sex and date of death flow back to the case (the form is the record of
the interview). `org_<level>_code` stays server-injected at submission.

| WHO question | Source | Locked |
|---|---|---|
| `Id10010` / `Id10010c` interviewer name and id | signed-in user (`digitva-dyk`) | yes |
| `Id10002` / `Id10003` HIV / malaria area | district presets (`digitva-dhc`, done) | yes |
| `Id10017` / `Id10018` given name, surname; `Id10019` sex | case | no |
| `Id10021` date of birth, or age group and age fields | case | no |
| `Id10022` = yes, `Id10023_a` date of death | case | no |
| `Id10058` where the deceased died | case `place_of_death`, mapped to WHO choices | no |
| `Id10057` where the death occurred (country, state, district, village) | org path names of the case's unit plus the case address | no |
| `Id10055` usual residence | case address, else the same org path | no |
| `Id10007` respondent name | case informant name | no |
| `Id10061` / `Id10062` father's / mother's name | new optional registration-form fields (`digitva-vzk.1`) | no |
| `Id10010a` / `Id10010b` interviewer age / sex | new user-profile fields: year of birth (age computed at interview time) and sex (`digitva-vzk.2`, `digitva-vzk.3`) | yes |

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
  started each case. There is no reassignment.

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
service; 3 direct start creates the case and one worklist API; 4 worklist UI
and register form; 5 appointments, contact attempts, pause; 6 duplicate check
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
  `POST /intake/api/cases/<death_id>/flags`.
- **Submission rule unchanged** (valid form and `Id10013`) until the
  `interview_outcome` question is built; a submission moves its case to
  `submitted`. A direct start whose answers lack the minimum identity is
  refused at submit (422).
- **Lists:** `GET /intake/api/deaths` stays the death register
  (`source = register` only) and still accepts the old status names
  `va_in_progress` and `va_submitted` as filters. The worklist is
  `GET /intake/api/cases` (`mine`, `state`, `limit` up to 200, `cursor`), sorted
  by last activity until phase 5 adds visit dates; its rows carry no informant
  name, phone or address.

### Open design items (questions for the owner)

- **Date of death unknown** (found building phase 3). A direct start whose
  respondent knows only the year of death (`Id10022` = no, `Id10024`) never
  gets a date of death, so it cannot leave `draft_identity` and cannot be
  submitted. Should the minimum identity accept a year of death, and how
  should the case store it?

## Not yet implemented

- Attachments (phase 2), the validator sidecar (W1), offline mode, native
  app. Of "Case worklist and interview states" above, the case state machine,
  flags and the worklist API are built (phases 2 and 3); the worklist page,
  team drafts, supervisor powers and views, contact attempts, the
  `interview_outcome` question, first-complete-submission and offline capture
  are **not implemented**. Offline capture is native-app work under Path B of
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
