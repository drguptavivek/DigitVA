---
title: Web Intake Policy (WHO VA 2022 questionnaire in DigitVA)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-29
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
  since `date_of_death` is a required death-register field today, that never
  happens in practice and only `dateOfDeath` is sent (`digitva-dyk`,
  2026-09-29). A thrown error previously meant the page silently prefilled
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
  consent question (`Id10013`) is answered. Server-side re-validation with
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

## Not yet implemented

- Attachments (phase 2), the validator sidecar (W1), offline mode, native
  app. ("Unit-scoped listing refinements" was struck on 2026-09-19: there was
  no concrete item behind it, and `list_deaths` already scopes by unit
  grants.)

Web intake is path A of
[Field Data Collection Policy](field-data-collection.md), which fixes the rule
this path already follows — answers are never persisted in the browser — and
sets the conditions an offline native collector must meet before it may hold
interview data on a device.
