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

## Done (2026-09-18): PII flags made reproducible

`mas_field_display_config.is_pii` drives one thing only:
`_filter_export_payload()` redacting keys from the data-manager CSV export. It
does not mask the coding screen — identifier questions are excluded there by
never being mapped (`_build_fieldsitepi` requires a non-NULL `subcategory_code`).

Flags existed in the live database (11 fields on WHO_2022_VA, set by hand in the
admin panel and inherited by the cloned WHO_2022_VA_SOCIAL), but nothing in the
seed path reproduces them: the Excel mapping source has no `is_pii` column, so a
fresh install or a mapping reseed starts with none. Four fields were unflagged
altogether: `Id10010c`, `Id10073` (national identification number) and web
intake's `abha_number` / `abha_address`.

- `app/services/pii_field_registry.py` — declarative field -> pii_type registry,
  idempotent `apply_pii_field_registry()`. Creates rows with NULL
  category/subcategory for unmapped fields, so they are visible to redaction and
  invisible to the coding screen. Never replaces a `pii_type` an operator chose.
- Migration `b8e3d1f7a2c4`; `flask seed run` reapplies it after a mapping reseed.
- `tests/services/test_pii_field_registry.py` (9 tests). Whole suite 1154 passing.
- `docs/current-state/field-mapping-system.md` corrected: it claimed flagged
  fields were "masked in non-PII views", which was never true.

Downgrade removes only the rows the migration created; flags on pre-existing
rows are left in place rather than cleared, since there is no record of which
ones predate it and clearing would silently widen the export.

Next: the collection policy (online = no PII at rest, app = encrypted at rest),
then the collector app.

## Done (2026-09-18): XLSForm -> instrument converter, and engine type coverage

Decision: DigitVA keeps its own engine (`vendor/who-va-2022`, ours to extend)
rather than adopting ODK Central's `@getodk/xforms-engine`. PHMRC and the
Ballabgarh form will be authored as ODK XLSForms, so the XLSForm becomes the
single authoring source: publish to ODK Central for ODK collection, convert the
same workbook into an instrument for DigitVA's clients.

- `app/services/xlsform_instrument_builder.py` — survey/choices/settings ->
  instrument JSON. Expressions pass through as raw XLSForm source; the engine
  already evaluates ODK's expression language, so relevance, constraint and
  calculation never need interpreting here.
- `tests/services/test_xlsform_instrument_builder.py` (11 tests). Conformance is
  measured, not asserted: the WHO 2022 instrument is rebuilt from
  `whova2022_xls_form_for_odk.xlsx` and compared field by field to the
  hand-audited JSON. 30 differences remain, every one the package departing from
  its own workbook, recorded in `DEVIATIONS`. Four are undocumented upstream and
  worth reporting: `Id10007` and `Id10010` gained app-added name regex
  constraints, `Id10477`-`Id10479` choice lists differ, and the `consented`
  section was relabelled "Interview completion".

Engine extended for the ODK types DigitVA needs, since the WHO forms may use
them: decimal, time, datetime, barcode, range, geopoint (plus phonenumber and
email as metadata). Touched `types.ts` (AnswerDataType, QuestionControl),
`engine/instrument-model.ts` (the control -> dataType allow-list, which is what
actually gates instrument compilation), `engine/validation.ts` (decimal, time
and geopoint checks) and `ui/question-controls.tsx` (Decimal, Time, DateTime,
Barcode, Range, GeoPoint controls; two new platform services,
`captureLocation` and `scanBarcode`).

Verification: `tooling/who-va-2022 && npm run check:types` — 19 functional
checks through the built validator bundle (the vendored engine has no
node_modules here, so its vitest suite cannot run in this repo).

Not done: geotrace, geoshape, start-geopoint, video, background-audio, rank —
the converter refuses each by name with the engine work it needs. Map
appearances for geopoint (`maps`, `placement-map`, `hide-input`) are not
implemented; the control captures a value through the host's location service
and accepts manual entry.

## Done (2026-09-18): appearances and inline markup

`node_modules` installed in `vendor/who-va-2022`, so the engine's typecheck and
vitest suite run in this repo for the first time. Both immediately earned their
keep — see "caught by verification" below.

**Appearance parsing.** `src/ui/appearance.ts`. Appearances were compared with
`===`, so only a lone token ever matched and every combination
(`columns-3 no-buttons`) was ignored. All appearance reads now go through
`hasAppearance`/`columnLayout`.

Implemented: `numbers`, `masked`, `multiline`, `thousands-sep` (display only —
the submitted value stays a plain number), `month-year`, `year`, `search`,
`columns`, `columns-n`, `columns-pack`, `no-buttons`, `likert`, `picker`,
`rating`, `draw`, `signature`. Drawing uses a new host service
`captureDrawing(question, data, mode)`, as camera and audio already do.

`no-calendar` needs no engine change: it asks for a spinner-style picker rather
than no picker, and the host owns the picker and receives `question`, so it
reads the appearance itself.

Not implemented, by decision: the six alternative calendars (ethiopian, coptic,
islamic, bikram-sambat, myanmar, persian) and `image-map`.

**Inline markup.** `src/ui/rich-text.ts` + `rich-text-view.tsx`, 17 tests.
337 of 449 WHO questions carry HTML in their guidance. The presentation layer
flattened it with a tag-stripping `plainText`, so no tags leaked but the blue
guidance colour, emphasis and links were silently discarded. Labels, hints and
guidance now render through `RichText` via a new non-stripping `localizedRich`;
`localized` stays for places that need a plain string. Supports `**bold**`,
`*italic*`, headings, links, `<b>/<strong>/<i>/<em>/<u>/<br>` and
`<span style="color:...">`, plus entity decoding. It produces styled spans
rather than injecting HTML, so it works on React Native and cannot execute
hostile markup from a form definition.

Choice labels render their markup too: `RichText` is passed into the controls
factory as an optional primitive, so a host that does not supply one still gets
the previous tag-stripped text.

The six new button labels (`Scan`, `Get location`, `Update location`, `Sign`,
`Re-sign`, `Draw`, `Redraw`) are i18n keys, not literals. Adding them was safe:
`WhoVaUiTranslations` is `Record<string, Partial<WhoVaUiMessageTemplates>>`, so
a host supplying custom messages is unaffected by new keys.

**Caught by verification, not by review:**

- `tsc` found two `possibly undefined` errors in the geopoint validator.
- `<br>` was parsed as `<b>` with attributes "r": in `(b|strong|i|em|u|br|span)`
  the `b` alternative matches first. Fixed with ordering plus a `(?=[\s/>])`
  boundary. A parser test caught it.
- The control-coverage test caught the six new controls missing from the
  exported registry.
- `tests/native-renderer.test.tsx` caught a semantic misreading: it asserts
  `pickDate` is still called for a `no-calendar` question, which is correct
  ODK behaviour and contradicted my first implementation.

Engine suite: 13 failed / 646 passed (659) — the same 13 that fail at HEAD
(`.tasks/who-va-engine-test-suite-stale.md`), no regressions. Python suite:
1198 passed. Bundle rebuilt at 1097 KB.

## Done (2026-09-18): first browser run, and the draft-save path

**The questionnaire page was opened in a browser for the first time.** The
bundle loads and the form renders. The rich-text work is confirmed live: five
elements compute to `rgb(0, 0, 255)`, so the WHO guidance renders as blue text
rather than being stripped.

Found while there: `<who-va-2022-form>` exposes only `lockedQuestionNames`,
`draftStore` and `platform` — **no `instrument`**. The element is hardwired to
the WHO instrument, so nothing the XLSForm converter produces can be rendered
through it yet. That is a blocker for PHMRC and Ballabgarh, not for WHO 2022.

**Draft saving.** Two defects, both measured in a browser against the page's own
code (a harness built by extracting the template's script with the Jinja values
stubbed):

1. A rejected save poisoned the queue. `saving = saving.then(...)` stays
   rejected forever, so every later `.then()` skipped its callback — one failed
   PATCH silently stopped all saving for the rest of the interview. The queue
   now clears the rejection before chaining; each caller still learns about its
   own failure.
2. One PATCH per keystroke. The form awaits `draftStore.save()` before calling
   again, so the store's latency sets the callback rate; with an immediate
   store that is a request per keystroke.

Measured, before -> after:

| | before | after |
|---|---|---|
| on mount | 2 (identical payloads) | 1 |
| 7-keystroke burst, then pause | 7 | 1 |
| 39 keystrokes over 6s continuous | 39 | 5 |

Also: no request at all when a section's answers are unchanged; submit flushes
the pending window before posting; unload flushes with `fetch(keepalive)`
because `sendBeacon` cannot carry `X-CSRFToken`.

Because the form serializes on the save promise, the sustained write rate is
about one per `SAVE_DEBOUNCE_MS` (2000) rather than one per pause. The
max-wait bound is kept as a guard but does not engage under that serialization.

## Done (2026-09-18): instrument identity, and rendering a converted instrument

The XLSForm `settings` sheet is provenance, not an identity DigitVA can key on:
`form_id` and `version` belong to whoever authored the workbook and change on
every republish, so binding field and choice mappings to them would silently
re-point a project's mappings. The converter now takes DigitVA's own key.

- `build_instrument_from_xlsform(path, form_type_code=...)` emits
  `formTypeCode` (upper-cased, e.g. `WHO_2022_VA`, matching
  `mas_form_types.form_type_code`) as the mapping key, and records the settings
  sheet under `source` = `{formId, formTitle, formVersion, file}` for audit
  only. Omitting the code logs a warning and produces an instrument with no
  mapping key rather than guessing one.
- `InstrumentDefinition` gains optional `formTypeCode` and `source`
  (`InstrumentSource`).
- `<who-va-2022-form>` gains an `instrument` property and an
  `instrumentIdentity` getter (`{formTypeCode, id, title, version}`). Without
  it the element was hardwired to the built-in WHO instrument and nothing the
  converter produced could be rendered.

Rendering a host-supplied instrument needed more than the property: the element
builds its session in the constructor and `setInstrument` only accepts a
*translation* of the same contract — it threw "A session language change cannot
alter the instrument semantic contract". The element now tracks `sessionBase`
and builds a new session when the questionnaire itself changes; answers do not
carry across a contract change, which is the only safe reading.

Verified in a browser: the WHO workbook converted with
`form_type_code="who_2022_va"` renders through the element,
`instrumentIdentity` reports `WHO_2022_VA` with the source id/title/version.

Worth knowing for PHMRC/Ballabgarh: a converted instrument is the *raw* XLSForm.
The language choices render as "English, Language 2, Language 3" — the WHO
workbook's placeholders — because DigitVA's extension questions (narration
languages, ABHA, `md_im1..30`, `ds_im1..5`) are composed in separately by
`src/instrument.ts`. A converted form is DigitVA-ready only once those fields
are either authored into its XLSForm or composed on after conversion. Authoring
them into the workbook keeps the XLSForm as the single source.

Engine suite: the full run is flaky. Three consecutive runs gave 14, 13, 13
failures; the extra one
(`web-validation-navigation > scrolls to and focuses the first invalid question`)
passes in isolation and is unrelated to these changes. The stable 13 are the
stale-expectation failures in `.tasks/who-va-engine-test-suite-stale.md`.
Python suite: 1209 passed.

## Done (2026-09-18): deactivated organization unit is refused at submit

Raised by the organization-model session. Since phase 4, the routed unit decides
who may code, so a submission that fails to route is visible to **no coder** in
a project with an organization tree — not merely untidy.

A unit can be deactivated between starting a draft and submitting it. Routing
only attributes a submission to a live unit, so that case would fall back to the
mapping's unit or stay unrouted, silently.

- `submit_draft` now refuses when the draft's unit is missing or inactive, and
  says which unit and what to do. The draft survives, so no answers are lost.
- `_unit_context` filters ancestors to active units: planting a dead unit's code
  in the payload is inert for routing and misleading in the stored record.
- Tests: `test_submit_is_refused_when_the_unit_was_deactivated`,
  `test_a_deactivated_unit_contributes_no_code_to_the_payload`.

Confirmed from that session and recorded here so it is not re-litigated:
routing is by organization codes only — submitter name is data, never a routing
key; `_unit_context` must keep deriving field name and code from the same level
row (there is no ODK preflight for a web form to catch a hardcoded name); and a
project with no tree routes to NULL by design. For a unit picker in the intake
UI, use `org_grant_service.scope_unit_ids(user_id, role)` — `codeable_unit_ids`
answers a coding question, not a form-filling one.
