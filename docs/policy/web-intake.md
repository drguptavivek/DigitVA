---
title: Web Intake Policy (WHO VA 2022 questionnaire in DigitVA)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-18
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
  gate never widens scope.
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
- **Questionnaire content**: the WHO instrument plus DigitVA's extension
  questions (`abha_number`, `abha_address`, `narr_language`, `imagenarr`,
  `md_count`, `md_im1..30`, `ds_count`, `ds_im1..5`). Context fields
  (`Site`, `unique_id`, `survey_state`, `survey_district`,
  `org_<level>_code`, submitter metadata) are injected by the server at
  submission, never typed by the interviewer.

## Submission

- A draft is submitted only when the questionnaire reports `valid` and the
  consent question (`Id10013`) is answered. Server-side re-validation with
  the package's own validator is a planned sidecar (decision W1); until it
  exists the server performs structural checks only.
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

## Not yet implemented

- Attachments (phase 2), the validator sidecar (W1), unit-scoped listing
  refinements, offline mode, native app.
