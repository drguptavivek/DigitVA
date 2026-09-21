---
title: VA Web Form Options Contract
doc_type: policy
status: active
owner: DigitVA Data Collection
last_updated: 2026-09-21
---

# VA Web Form Options Contract

Everything the DigitVA VA web form accepts as an option, in one place, so the
route that renders a form knows exactly what it may supply and the project API
knows exactly what it must serve.

The rule this document exists to enforce: **the form itself decides nothing.**
It renders the instrument it is given, in the language it is told, with the
extensions the project enabled. Every choice belongs to project configuration
and arrives as an option. Anything the form decides for itself is a default
that some project will eventually need to override, so it is listed here even
where today's value is a constant.

## Where an option can come from

| Tier | Source | Changes per |
|---|---|---|
| 1. Instrument | The compiled instrument (`form_type_code`) | Questionnaire |
| 2. Project | Project settings, served by the organization/project API | Project |
| 3. Session | The route, from the draft and the signed-in user | Draft / user |

A tier-2 option must never be hardcoded in a template or inferred from the
instrument. That is the whole point of the tier: two projects running the same
questionnaire differ only by tier-2 options.

## The complete option surface

### Tier 1 — which questionnaire

| Option | Type | Set today | Notes |
|---|---|---|---|
| `instrument` | `InstrumentDefinition` (property) | **Yes** — selected by the default form type's `instrument_code` (2026-09-19) | The host must pass this once a second *standard instrument* is bundled. Built offline; never compiled at request time. |
| `instrument_code` | string, served per form type | **Yes** (2026-09-19) | The standard instrument a form type layers on, read from `mas_form_types.base_instrument_code`; `null` when nothing is bundled for that form type, which the page renders as an error. |
| `formTypeCode` | string, inside the instrument | Emitted by the builder | The mapping key for the instrument's own identity. Not the instrument selector — `instrument_code` is. |
| `enabled_extensions` | string[] | **Yes** — served, derived from project settings (2026-09-19) | `digitva_core`, `social_autopsy`, `intake_screen`, `geography`, `narration_language`, `death_summary`, `medical_records`, `abha`. Decides which sections exist. |

**DigitVA form types are layers, not instruments.** `WHO_2022_VA_SOCIAL` and
any future `WHO_2022_VA_*` are layers on the one standard WHO 2022 VA
instrument; which layers apply is `enabled_extensions`, not a different
questionnaire. So the intake page keys `INSTRUMENTS` on `instrument_code`, and
O1's "pre-built variants" means pre-built **per standard instrument**, never
per layer.

**Landed 2026-09-19:** `mas_form_types.base_instrument_code` (String(32),
nullable) records which standard instrument a form type layers on, backfilled
from the naming convention that stood in for it. `instrument_code_for()`
(`app/routes/api/organization.py`) reads the column and nothing else — **the
prefix rule is gone**, so a `WHO_2022_VA*` code whose column is NULL now
resolves to `null` rather than to the WHO instrument. A new form type records
the column as part of
[New Form Type Onboarding](new-form-type-onboarding.md); the form-type admin
list and `flask form-types list` show it, and the form-type PATCH sets it.

### Tier 2 — project configuration

| Option | Type | Set today | Notes |
|---|---|---|---|
| `locale` | string (attribute) | **Yes** — `default_locale` from the project (2026-09-19) | Always `en`, the instrument's base language. Decided 2026-09-19: there is no per-project default; the stored column is honoured only when it names a locale the instrument has, and is otherwise `en`. |
| `available_locales` | string[] | **Yes** — served (2026-09-19) | `en` plus the languages the project adds, restricted to the instrument's **servable** locales -- active, or `in_review` (changed 2026-09-21; see "English alongside the translation") -- (`mas_instrument_locales`, queried by `app/services/web_form_instruments.py`). Not drawn from `mas_languages`; those codes describe narration recordings. |
| `uiTranslations` | `WhoVaUiTranslations` | **No** | Chrome strings (buttons, validation): "Next", "Required", the date picker. **Separate from instrument translations and staying separate** — they belong to the engine, not to a questionnaire, so they are not rows in `map_instrument_translations` and importing a workbook never touches them. |
| `narration_languages` | `{code,label}[]` | **Yes** — served (2026-09-19) | Options for `narr_language` — the language the narrative was *recorded* in. Distinct from `locale` and from the instrument's own "Interview language" question. Per-project checkboxes. |
| `geography` | level + unit codes | Partly — via the units API | Feeds `survey_state`/`survey_district`/`survey_block` and `org_<level_code>_code` routing. Comes from the project's organization hierarchy. |
| `show-guidance` | boolean (attribute) | **Yes** — served and passed when true (2026-09-19) | Whether source guidance notes render. An interviewer-training setting. |
| `attachment_policy` | image/audio/PDF limits | **No** — engine defaults | Size and dimension ceilings. |
| `web_intake_form_type_id` | uuid | **Yes — project setting** (2026-09-19) | Which form type the project's browser questionnaire carries. Must be an active form type with a `base_instrument_code` and a confirmed PII set; NULL means `WHO_2022_VA`. |
| `intake_screen` | note text | **Yes — project setting** (2026-09-19) | A welcome note shown before the questionnaire, `web_intake_intake_note`. NULL is the system default text (`DEFAULT_INTAKE_NOTE`), `""` is no welcome screen. In `enabled_extensions` exactly when the resolved note is non-empty; the text is served as `intake_note`. |
| `translation_versions` | `{locale: int}` | **Yes** — served (2026-09-19) | The version of every locale this project's instrument currently serves, `en` at 0. A page caches a locale's strings and re-fetches only when its version moves. |
| `death_summary` | boolean | **Yes — project setting** (2026-09-19) | Optional upload of death summary documents, `web_intake_death_summary_enabled`, on for every project. Never a mandatory response; rendering waits for attachments phase 2. |
| `medical_records` | boolean | **Yes — project setting** (2026-09-20) | The medical-record fields (`md_available`, `md_count`, `md_im1`..`md_im30`), `web_intake_medical_records_enabled`, on for every project. A project may opt out. |

### Tier 3 — session and runtime

| Option | Type | Set today | Notes |
|---|---|---|---|
| `draft-id` | string (attribute) | Yes | |
| `draftStore` | `WhoVaDraftStore` | Yes | Debounced PATCH to the intake API. |
| `auto-save-draft-on-change` | boolean (attribute) | Yes | |
| `auto-save-draft-interval-ms` | number \| false | No — default | |
| `initialData` / prefill answers | `SubmissionData` | Yes, via `PREFILL.answers` | |
| `lockedQuestionNames` | string[] | Yes, via `PREFILL.lockedQuestionNames` | Answers carried from death registration that the interviewer may not contradict. |
| `platform` | `WhoVaPlatformServices` | **No** | Capture hooks: audio, image, file, date picker, barcode, geopoint, drawing. Web supplies browser implementations; the native app supplies its own. This is the single seam between the shared engine and the host platform. |
| `org_unit_id` | uuid | Yes, via the picker | The deepest unit selected. Server re-validates against grants regardless of what the client sends. |
| `locale (user choice)` | string (attribute) | **Yes** (2026-09-19) | The interviewer's working language, chosen on the intake page from `available_locales`, remembered in the browser (`localStorage` key `digitva.intake.locale`, last choice wins), and applied by setting the component's `locale` attribute. Falls back to the project default when the remembered code is not available. |

## What the project API must serve

The options in tier 2 are per-project and the form route has no other way to
learn them. They belong next to the organization tree, which is already the
per-project configuration the intake page fetches:

```
GET /api/v1/organization/<project_id>/form-options
```

**Implemented 2026-09-19** in `app/routes/api/organization.py`, on the same
blueprint and behind the same grant check as `/units`. Backed by eight columns
on `va_project_master` (`web_intake_default_locale`,
`web_intake_available_locales`, `web_intake_narration_languages`,
`web_intake_show_guidance`, and since 2026-09-19 `web_intake_form_type_id`,
`web_intake_intake_note`, `web_intake_death_summary_enabled`, and since
2026-09-20 `web_intake_medical_records_enabled`), and accepted by
the project POST and PUT in `app/routes/admin.py`. The POST also applies
`WEB_PROJECT_DEFAULTS` (`app/services/web_intake_service.py`) to every web
setting a create payload omits when `web_intake_mode` is not `off`.

`available_locales` is the intersection of what the project stores and what
the bundled instrument has translations for, never the `mas_languages` list.
Three of the four columns are edited from the Projects admin panel
(`app/templates/admin/panels/projects.html`): available languages, narration
languages and guidance. The default locale is not exposed there — it is always
`en` — and the panel builds its available-language checkboxes from
`GET /admin/api/web-form-locales`, keeping `GET /admin/api/languages` for
narration only.

```jsonc
{
  "project_id": "...",
  "config_version": "...",          // moves when any option changes, like tree_version
  "enabled_extensions": ["digitva_core", "geography", "narration_language"],
  "form_types": [                    // form types live for this project
    {"form_type_code": "WHO_2022_VA_SOCIAL", "instrument_code": "WHO_2022_VA",
     "title": "...", "is_default": true}
  ],
  "intake_note": "Before you begin: …",   // null when the welcome screen is off
  "default_locale": "en",
  "available_locales": [{"code": "en", "label": "English"}, {"code": "hi", "label": "Hindi"}],
  "translation_versions": {"en": 0, "hi": 7},   // revalidate cached strings against this

  "narration_languages": [{"code": "hi", "label": "Hindi"}],
  "show_guidance": false
}
```

Notes on the shape:

- `config_version` exists for the same reason `tree_version` does: a client
  caches the options and revalidates, so a settings change reaches a page that
  is already open.
- Geography is **not** repeated here. It is the organization tree, served by
  `GET /api/v1/organization/<project_id>/units`, and duplicating it would
  create two sources for the codes that drive routing.
- `form_types` are the distinct active form types the project collects on:
  those reached through `map_project_site_odk`, **union** those of the
  project's active `form_source='web'` `va_forms` rows, plus the configured
  web questionnaire when the project collects on the web and no web form row
  exists yet. Exactly one is the default: the configured web questionnaire
  when `web_intake_mode` is not `off` (`web_intake_form_type_id`, falling back
  to the existing web row's type and then to `WHO_2022_VA`), otherwise the
  form type linked to the most sites, ties broken by `form_type_code` so the
  answer is stable. Each carries `instrument_code`, the standard instrument it
  layers on, or `null` when nothing is bundled for it. A configured form type
  that has been deactivated is skipped here rather than raised on — the
  interviewer's page degrades to the fallback questionnaire, and the readiness
  check reports the misconfiguration.
- `enabled_extensions` is derived, never stored: `digitva_core` always;
  `social_autopsy` from `social_autopsy_enabled`; `geography` when the project
  has an organization hierarchy; `narration_language` when narration languages
  resolve to a non-empty list; `abha` when the default form type has an active
  `abha_number` field display config; `intake_screen` when the resolved
  welcome note is non-empty; `death_summary` from
  `web_intake_death_summary_enabled`; `medical_records` from
  `web_intake_medical_records_enabled`.
- `intake_note` is the text the `intake_screen` extension renders, or `null`
  when the project turned the welcome screen off.
- `available_locales` is the intersection of what the project allows and the
  instrument's **active** locales. The form must tolerate a locale it has no
  strings for by falling back, not by failing.
- `translation_versions` carries one entry per served locale so a page that is
  already open can tell whether its cached strings are stale without
  downloading them. `en` is always present at version 0: it is the
  instrument's own language and has no rows.

### Instrument translations: the delivery contract

**Implemented 2026-09-19 (WP6).** Translations are server data and are fetched
separately from the instrument, by every frontend alike — the browser form
today, the native app later:

```
GET /api/v1/instruments/<instrument_code>/translations/<locale>
```

`login_required`. Returns
`{"instrument_code", "locale", "version", "questions": {name: {label, hint, guidance_hint}}, "choices": {"list/value": {label}}}`
with a weak `ETag` over the version, so a client revalidates with
`If-None-Match` and gets a 304 when nothing moved. An unknown locale, an
unknown instrument and a locale that is neither active nor `in_review` are
all 404 (changed 2026-09-21: an `in_review` locale is served, always with
English beside it -- see "English alongside the translation" below). Activation is not gated
on how much of the locale is translated -- an untranslated string is absent
from this payload, so the form falls back to English for that string alone.
`en` is always served, at version 0 with no strings, because the bundled
instrument is already in English.

The intake page applies the result client-side: `applyTranslations` in
`app/static/js/intake/translations.js` is a pure function that returns a copy
of the pre-built instrument with `label[locale]`, `hint[locale]` and
`guidance[locale]` set on sections, questions and choices. Switching locale
re-fetches and re-applies **from the same base copy**, so nothing accumulates
across switches, and the draft records the new `locale` and
`translation_version` through the existing PATCH.

### English alongside the translation

**Decided 2026-09-21 by the owner (`digitva-mxn`), prompted by the translation
audit (`digitva-fb5`).** The deployed ODK workbooks pack English and the
translation into one cell, so an ODK interviewer always reads both, and a
wrong translation sits directly under the right English. The web form served
the translation alone and so lost that cross-check. It is restored:

1. **When a non-English locale is shown, the English is shown beside it** —
   question labels, hints and choice labels. It is a secondary, muted line in
   `lang="en"`, rendered through the same rich-text path as the translation,
   and omitted where the English is the only text (an untranslated string
   already falls back to English).
2. **A toggle, on by default.** "Show English" sits beside the language
   picker; the interviewer's choice is remembered per browser. Not a project
   setting.
3. **An `in_review` locale is offered to interviewers, with English forced
   on.** It is labelled as under review in the picker and the toggle cannot
   be switched off for it. `draft` locales are never served. This amends
   "Approval before activation" in
   [VA Form Project Configuration Policy](va-form-project-configuration.md):
   approval still gates **activation** and serving a locale on its own;
   an unapproved `in_review` locale may only ever be read under its English.
   A project still opts in through `web_intake_available_locales`.
4. **Display only.** Nothing in a submission changes: answers are the same
   choice values, and `intake_locale` / `intake_translation_version` are
   recorded as before.

### Adding a language

**Changed 2026-09-19 (WP6).** A display language is no longer vendored into the
instrument bundle and is no longer a code in a Python registry. It is data:

1. **Import it.** `flask instrument-translations import <instrument_code>
   <locale> <workbook>`, or upload the workbook in the Instrument Translations
   admin panel. Importing a questionnaire source is a reviewed one-time
   activity, not a policy gate the importer enforces (decided 2026-09-20): any
   readable workbook is accepted for any locale. The importer merges by
   question `name` and by `list_name`/`name` for choices, splits cells that
   pack English and the target language on one line, and reports every
   reference item the workbook lacks and every workbook item the reference
   lacks. It can never create a question.
2. **Record the source.** Add the language to the "Translation sources" table
   in
   [VA Form Project Configuration Policy](va-form-project-configuration.md) —
   language, locale code, the one workbook it was reviewed against, project,
   ODK form id, download date and who assigned it. This is provenance for a
   human reader, not something the importer reads back.
3. **Approve it, then activate it.** Activation is refused until a human has
   approved the locale (decided 2026-09-20: see "Approval before activation"
   in
   [VA Form Project Configuration Policy](va-form-project-configuration.md)).
   Move it through its lifecycle — `flask instrument-translations lifecycle
   <instrument_code> <locale> in_review`, then `... approved --approved-by
   <user id or email>` — or use the **Send for review** / **Approve** buttons
   in the admin panel, then `flask instrument-translations activate
   <instrument_code> <locale>` or the **Activate** button (disabled in the
   panel until the locale is approved). Activation itself is still an
   explicit administrative decision, independent of coverage (changed
   2026-09-19: see "Activation is explicit, not gated on coverage" in
   [VA Form Project Configuration Policy](va-form-project-configuration.md));
   coverage is still shown, for context, on every locale's row, and neither
   step is gated on it.
4. **The project opts in.** An active locale is only offered by a project that
   lists it in `web_intake_available_locales` (or stores NULL, which means all
   of them).

**Handing a language to a translator.** Step 2 seeds a language; refining it is
done in **XLIFF 2.0**, the industry-standard interchange every CAT tool reads
(decided 2026-09-19; the scheme and the rules are in
[VA Form Project Configuration Policy](va-form-project-configuration.md) →
"Interchange format"). Export the locale
(`flask instrument-translations export-xliff <instrument_code> <locale>`, or
the **XLIFF** button on the language's row in the admin panel), send the `.xlf`
out, and import the returned file (`import-xliff`, or **Import XLIFF**). Choose
`--as edited` for a reviewed file that should outrank a later workbook
re-import, `imported` for a bulk hand-back that should not. An XLIFF import
cannot add a language or a question: a unit whose id the reference form does
not have is reported and skipped.

**Where no translation exists the form shows English.** Nothing falls back to
a blank. The serving payload
(`GET /api/v1/instruments/<instrument_code>/translations/<locale>`) omits an
item it has no string for rather than sending an empty one, the client-side
apply (`app/static/js/intake/translations.js`) sets a locale's text only when
it is a non-empty string, and the bundle's `localizeText` then resolves label
candidates in the order **locale, base language, `en`**
(`localeCandidates`, `vendor/who-va-2022/src/i18n.ts`). So a partially
translated language renders every translated string in that language and every
other one in English, in the same form, and a half-covered language can never
blank a question. Pinned by `tooling/who-va-2022/tests/translations.test.mjs`
("where no translation exists the form falls back to English") and
`tests/services/test_instrument_translation_xliff.py`
(`InstrumentTranslationEnglishFallbackTests`).

Corrections are made string by string in the panel: the edit is marked
`edited`, survives the next re-import, bumps the locale's version and is
written to the log with the item key and the old and new text. Every
submission records `intake_locale` and `intake_translation_version`, so what
the respondent saw remains reconstructible.

Adding a row to `mas_languages` does *not* add a web form language; that list
is for narration recordings, and its codes are a different axis (`khasi` there,
`kha` here). Nothing maps between them.

## Submission validity: the server no longer only trusts the client

**Landed 2026-09-20 (beads digitva-cal.2, digitva-aiy.1).** The browser is
still the only engine that gates data entry — a field interviewer's session
is validated exactly as before, question by question, as they type. What
changed is what happens once `completion.valid` reaches the server in
`POST /intake/api/drafts/<id>/submit`.

`app/services/web_form_relevance_service.py` is a second, independent
evaluation of the same composed instrument (WHO base plus every enabled
DigitVA extension) built from
`vendor/who-va-2022/src/generated/who-va-2022.server-instrument.json`
(`tooling/who-va-2022/build-server-instrument.mjs`) and parsed with
`app/services/xform_expression_evaluator.py` — the Python port kept honest
by the conformance corpus (docs/policy/xform-expression-evaluator.md). It
ports `isQuestionRelevantWithCalculatedData` / `applyCalculations` /
`validateAnswer`'s constraint check from
`vendor/who-va-2022/src/engine/validation.ts`, not a rewrite from scratch.

Two separate behaviours, both inside `submit_draft`:

1. **Accept and record, never refuse.** The server re-derives `relevant` and
   `constraint` over the client's raw submitted answers and records every
   place the two engines disagree — it never rejects a submission the client
   itself marked valid. If the client marks the questionnaire invalid, the
   server still refuses it, exactly as before; the client's boolean keeps
   its power in that one direction only. Each disagreement is
   `{"question": <name>, "rule": "relevant" | "constraint"}` — no answer
   value, ever — stored as `validation_err` on the *payload version*
   (`va_submission_payload_versions`, not `va_submissions`: a resubmission
   gets its own record) and returned in the submit response body. This is a
   diagnostic, deliberately: the owner's decision is to learn the real
   disagreement rate from live data before any later change considers
   refusing on it.
2. **Strip irrelevant answers at final submit only.** Before the payload is
   built, `strip_irrelevant_answers` removes answers to questions the server
   considers not relevant, resolved to a fixed point — stripping one answer
   can itself change what else is relevant (`md_available` gates `md_count`
   gates `md_im1..30`), so this iterates until nothing more is removed. This
   runs on the submitted copy only; a **draft** is never touched, so
   flipping a gate back during editing restores whatever was captured
   behind it. An attachment reference stripped this way is simply never
   added to the submission's attachment references — today that orphans no
   server storage, because nothing is uploaded server-side at this stage
   (`who-va-attachment:*` values are client-local blob ids); a later
   attachments-upload phase must check relevance the same way before
   uploading, not treat every reference on a draft as eligible.

Regenerate the server instrument after any change to
`vendor/who-va-2022/src/instrument.ts` or `digitva-extension.ts`:

```bash
cd tooling/who-va-2022 && npm run build:server-instrument
```

## Open questions

| # | Question |
|---|---|
| ~~Q6~~ | ~~Do the standardized project geography codes bind to `org_<level_code>_code` as the same codes, or through a mapping?~~ **Resolved 2026-09-19 by [VA Form Project Configuration Policy](va-form-project-configuration.md):** they are the same codes. `mas_org_unit.unit_code` *is* the geography code, there is no mapping table, and the web form fills `org_<level_code>_code` from `_unit_context`. |
| ~~O1~~ | ~~Pre-built instrument variants, or a filter over one superset at load?~~ **Resolved 2026-09-19: pre-built variants.** Not for tidiness — an instrument whose identity depends on request state cannot be tied back to what the respondent was actually shown, which makes a submission hard to defend evidentially. Immutable instruments, pre-built per *standard instrument* and selected by `instrument_code` — not one variant per form type, since form types are layers. |
| ~~O2~~ | ~~Who owns `attachment_policy`?~~ **Resolved 2026-09-19:** a system-wide constant until a project has a real reason otherwise; making it project-level later is additive. |

## Related

- `docs/policy/web-intake.md`
- `docs/policy/organization-model.md`
- `docs/planning/va-data-collection-plan.md`
