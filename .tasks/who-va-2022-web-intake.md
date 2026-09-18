# WHO VA 2022 web intake (who-2022-va package)

- Status: in progress (2026-09-18): phase 1 code written (models, migration e5f6a7b8c9d1, service, routes, pages, admin setting); automated tests now cover the service and the routes. Next: the two authorization gaps below, browser check of the form page, attachments (phase 2), validator sidecar (W1), mobile profiling
- Priority: high
- Created: 2026-09-17

## Goal

Fill the WHO 2022 VA questionnaire in a DigitVA web page using
`@drguptavivek/who-2022-va`, submit into the normal workflow, route by
`org_<level>_code`, keep ODK sync untouched.

## Context

Plan: `docs/planning/who-va-2022-web-intake-plan.md`. Depends on the
organization model (routing, unit prefill) for phase 3.

## References

- `app/services/va_data_sync/va_data_sync_01_odkcentral.py`
- `app/services/attachment_service.py`
- `app/services/workflow/transitions.py`

## Expected Scope

Spike, then phases 1–4 in the plan.

## Done (2026-09-18)

- `tests/services/test_web_intake_service.py` (24 tests): mode gating, interviewer
  scope, death-register validation and unique ids, draft section merge and envelope
  reassembly, submit -> `va_submissions` + active payload version + `smartva_pending`,
  attachment answers lifted out of the payload, web form vs ODK runtime sync.
- `tests/routes/test_intake_api.py` (12 tests): 401/403 gating for pages and API,
  CSRF on every state change, bootstrap, the register -> draft -> save -> submit
  happy path, owner-only form page, `WebIntakeError` status mapping, discard.
- Fixed: `sync_runtime_forms_from_site_mappings` keyed `forms_by_project_site` by
  (project, site) over every `va_forms` row, so an ODK mapping for a project-site
  that also has a web form overwrote the web form's `odk_form_id`/`odk_project_id`.
  Web-sourced forms are now excluded from the rewrite (their ids still reserve
  against `_next_form_id`).
- Fixed: `tests/migrations/test_attachment_state_backfill.py` seeded `va_forms`
  through the model at `PREVIOUS_HEAD`, which broke once the model gained
  `form_source`. It now inserts that row as SQL, like the attachment rows.
- `tests/conftest.py` creates `va_death_register_number_seq`; it is standalone DDL
  from migration `e5f6a7b8c9d1` that `create_all()` cannot produce.

## Fixed (2026-09-18): the two authorization gaps

`role_required("interviewer")` calls `is_interviewer()`, which resolved only
through `_get_granted_va_forms()` — existing `va_forms` rows, project and
project_site scope only. That broke two cases; both are fixed and tested in
`tests/routes/test_intake_api.py::WebOnlyProjectIntakeTests`.

1. **Web-only projects could not bootstrap.** The web `va_forms` row was only
   created lazily inside `start_draft()`, so a project with no ODK mapping had
   no form row, every interviewer was refused at `/intake/`, and nothing could
   ever create the row. `admin_update_project` now calls
   `runtime_form_sync_service.ensure_web_forms_for_project()` whenever
   `web_intake_mode` is set to a value other than `off`; it is idempotent and
   covers every active site of the project.
2. **Unit-scoped interviewer grants never satisfied the role gate.**
   `is_interviewer()` now also returns true for an active interviewer grant at
   `org_unit` scope. This opens the role gate only; `interviewer_context()` and
   `_require_scope()` still decide the project, site and unit, so scope is not
   widened. Policy: `docs/policy/web-intake.md` ("Role gate vs scope").

## Next

1. Browser walkthrough of the questionnaire page (draft store adapter, prefill,
   `lockedQuestionNames`, submit) — still unverified.
2. Phase 2 attachments: upload `who-va-attachment:` references through
   `attachment_service` (store-first), then `mark_attachment_sync_completed`.
3. Open decisions: W1 validator sidecar, W6 mandatory media, mobile performance
   profiling of the bundle.
