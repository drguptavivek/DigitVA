# Handoff

Updated 2026-09-18 (session: organization phase 1, ICD-11 catalog delegation, WHO VA 2022 web intake).

## State of `main`

- 91882f6 Organization model phase 1 (levels, units, cadres, workers, Organization panel, `flask org`).
- d3788eb ICD-11 MMS catalog, importer, `flask icd11`, read-only browser, form-level `icd_classification` (decisions D1/D4 as recommended; D3 allowability needs clinical sign-off; coding screen still ICD-10 only).
- b7480dc Organization phase 2, unit-scoped access grants (other session).
- 2fc60ea Vendored `vendor/who-va-2022` with DigitVA extension; bundle under `app/static/vendor/who-va-2022` built by `tooling/who-va-2022` (`npm ci && npm run check && npm run build`).
- This commit: web intake phase 1 (see below).

## Web intake phase 1 (this commit) — what exists and what is unverified

Code: `app/models/va_web_intake.py`, migration `e5f6a7b8c9d1` (applied on the dev DB), `app/services/web_intake_service.py` (deep module), `app/routes/intake.py` (`/intake/...`), templates `va_frontpages/va_intake*.html`, `interviewer` role (enum, grants constraint, `role_required`, admin scope sets, org grant roles, navbar, landing page), project setting `web_intake_mode` (admin Projects panel), `va_forms.form_source`, `ensure_web_runtime_form`.

Tests (41, all passing; whole suite 1145 green):

- `tests/services/test_web_intake_service.py` (24) — mode gating, interviewer scope, death-register validation and sequence-allocated unique ids, draft section merge and envelope reassembly, submit -> `va_submissions` + active payload version + `smartva_pending`, attachment answers lifted out of the payload, web form vs ODK runtime sync.
- `tests/routes/test_intake_api.py` (17) — 401/403 for pages and API, CSRF on every state change, bootstrap, register -> draft -> save -> submit, owner-only form page, `WebIntakeError` status mapping, discard; plus `WebOnlyProjectIntakeTests` for the two authorization fixes below.

Fixed while writing them:

- `sync_runtime_forms_from_site_mappings()` keyed its form lookup by (project, site) over every `va_forms` row, so an ODK mapping for a project-site that also had a web form overwrote the web form's `odk_form_id`/`odk_project_id`. Web-sourced rows are now excluded from the rewrite; their ids still reserve against `_next_form_id`.
- Web-only projects could not bootstrap: `is_interviewer()` resolves through `va_forms`, and the web form was only created lazily inside `start_draft()`. `admin_update_project` now calls `ensure_web_forms_for_project()` whenever `web_intake_mode` is set to something other than `off` (idempotent, every active site).
- Unit-scoped interviewer grants never satisfied the role gate (`_get_granted_va_forms()` ignores `org_unit` scope). `is_interviewer()` now also honours an active unit-scoped interviewer grant — role gate only; `interviewer_context()`/`_require_scope()` still decide project, site and unit.
- `tests/migrations/test_attachment_state_backfill.py` seeded `va_forms` through the model at `PREVIOUS_HEAD`, which broke once the model gained `form_source`; it now inserts that row as SQL, like the attachment rows.
- `tests/conftest.py` creates `va_death_register_number_seq` — standalone DDL from `e5f6a7b8c9d1` that `create_all()` cannot produce.

Still not verified: the questionnaire page has never been opened in a browser (draft store adapter, prefill, `lockedQuestionNames`, submit flow). `list_deaths` scoping for unit grants remains a first cut.

## First steps for the next session

1. Grant `interviewer` to a test user on a project with `web_intake_mode = both`, open `/intake/`, register a death, start the questionnaire, check section saves in `va_web_intake_draft_sections`, submit, confirm the case appears for coders.
2. Phase 2 attachments: upload `who-va-attachment:` references through `attachment_service` (store-first), then `mark_attachment_sync_completed`.
3. Decisions still open: W1 validator sidecar, W6 mandatory media; mobile performance profiling of the bundle.

## Cross-stream notes

- Migration chain: c8d2e4f6a1b3 -> b6edb1b7d01a -> f4b8dd6e3568 -> d9e3f5a7b2c4 -> e5f6a7b8c9d1. Always `flask db heads` before adding one.
- Shared test databases collide when two sessions run pytest at once; run the suite in chunks (services/routes/integration/migrations, then the rest) because the app container has a 756 MiB limit.
- Plans: `docs/planning/health-system-organization-model-plan.md`, `docs/planning/icd11-coding-screen-integration-plan.md` (parked), `docs/planning/who-va-2022-web-intake-plan.md`. Tasks in `.tasks/`.
