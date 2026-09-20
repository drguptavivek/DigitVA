---
title: Project configuration for web data capture and routing, and closing every open question
doc_type: planning
status: active
owner: DigitVA Data Collection
last_updated: 2026-09-20
---

# Project configuration for web data capture and routing, and closing every open question

Approved 2026-09-19. Beads issues: WP1 `digitva-6v1`, WP2 `digitva-xv9`,
WP3 `digitva-shz`, WP4 `digitva-mze`, WP5 `digitva-9ff`, WP6 `digitva-0by`.
Supersedes nothing; sits under `docs/planning/va-data-collection-plan.md`
as the configuration slice of its step 4 and the decisions register for
its open questions.

## Context

A project that collects VAs through the browser form in an organization
hierarchy needs several settings to line up before an interviewer can open
`/intake/`, fill the questionnaire, and have the case route to the right
unit and reach the right coders. Today those settings live in five places
(Projects, Project Sites, Organization, Access Grants, Form Types panels)
with nothing that says whether the project is ready, and one of them cannot
be set at all:

- **Defect: a web-only project has no questionnaire.** The form-options
  endpoint derives `form_types` from `map_project_site_odk`
  (`app/routes/api/organization.py:320-355`), so a project with no ODK
  mapping serves an empty list and the intake page stops with "This project
  has no questionnaire configured". Meanwhile `ensure_web_runtime_form`
  (`app/services/runtime_form_sync_service.py:238-277`) hardcodes the web
  form's type to `WHO_2022_VA`, so a project cannot choose the `_SOCIAL`
  layer. The web form's type must become project configuration. **Fixed by
  WP1 below**: a project-level web form type, read by both the web form
  materialiser and the form-options endpoint.
- **Routing is landed but unconfirmed end to end.** The consolidated plan
  still lists "project-scoped interviewer produces an unroutable case" as a
  known defect. `_require_scope` (`app/services/web_intake_service.py:235-279`)
  already refuses a tree project without a unit and the service tests cover
  it (lines 590-644), but no test follows a web submission from the picker
  to a unit-scoped coder's pick list. **Fixed by WP3**: an end-to-end test
  proves the route, and the stale defect row is struck.
- **The records carry open questions that are now answered.** The owner
  decided every one of them on 2026-09-19 (table below). **Fixed by WP4 and
  WP5**: the answers are written into the documents they were raised in;
  the ones that are project configuration are implemented in WP1.
- **Nothing tells an admin what is missing.** The readiness rules exist only
  as scattered checks. **Fixed by WP2**: one readiness endpoint, panel card
  and CLI command.

Out of this pass: attachments phase 2, validator sidecar W1, ICD-11 phases
3 to 6 (their decisions are recorded here; the work is planned separately),
native app. Settled and not revisited: form types are layers on the standard
instrument; `en` default plus instrument translations; closed projects
revoke grants; migrations import no app code; PII set confirmation rules.

## Decisions taken 2026-09-19 (to be recorded verbatim in the docs)

| Id | Where raised | Decision |
| --- | --- | --- |
| Q6 | `docs/planning/va-data-collection-plan.md`, `docs/policy/va-web-form-options.md` | Resolved by `docs/policy/va-form-project-configuration.md`: geography codes are the unit codes themselves, no mapping table; the web form fills `org_<level_code>_code` from `_unit_context`. |
| P2 | `docs/policy/va-form-project-configuration.md` | Admin saves the setting; that is the sign-off, recorded in the activity log. No pending state, no second approver. Instruments are pre-built per standard instrument, so a project change only selects layers. |
| W6 | `docs/planning/who-va-2022-web-intake-plan.md` | No media is mandatory. Audio narration is encouraged; a typed narrative is wanted; medical papers, discharge summaries and prior death certificates are uploaded as available. Mandatory-media rules, if ever, are project configuration added with attachments phase 2. |
| `intake_screen` | `docs/policy/va-web-form-options.md` | Becomes a project setting: a welcome note shown before the questionnaire, with a system default text; projects may edit or blank it. Served in `enabled_extensions` when non-empty. |
| `death_summary` | `docs/policy/va-web-form-options.md` | Becomes a project setting, on by default for every project: an optional media-upload section for death summary documents. A project can opt out at creation or later; an interviewer may leave it empty. Never a mandatory response. Rendering waits for attachments phase 2; the flag and the extension are served now. |
| `base_instrument_code` | `docs/policy/va-web-form-options.md`, `docs/policy/new-form-type-onboarding.md` | Added now as a column on `mas_form_types`, backfilled from the prefix rule; `instrument_code_for()` reads it. |
| D2 | `docs/planning/icd11-coding-screen-integration-plan.md` | Yes: one project setting `skip_initial_cod_assessment` governs coder Step 1 and reviewer initial COD. |
| D3 | same | Confirmed on record in commit `d9ae3b1` (2026-09-17): the WHO 2026 annex ICD-11 ranges are the authoritative ICD-11 source; the ICD-10 route (WHO's ICD-11 to ICD-10 mapping tables, then the ICD-10 policy) is advisory only, a cross-check whose disagreements go to clinical review. The curated source is therefore the WHO 2026 annex cause list already in the repo, `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv` (65 VA causes, each with its ICD-11 ranges). No per-code ICD-11 policy JSON exists on any branch (verified 2026-09-19: main, `origin/icd-11`, `claude/eloquent-gagarin-83c118`, `claude/kind-boyd-a06575`; the catalog migration seeds every row `unreviewed`, unselectable). The policy is produced by expanding those ranges over `mas_icd11_mms` linearization order (stem codes) with the same two rules already recorded for ICD-10: **a more specific code listed under one VA cause wins over a broader range it falls inside** (`docs/policy/who-2022-icd10-coding-allowability.md:173`), and **the 2026 annex mapping is its own scheme with its own JSON**, separate from the earlier mapping, exactly as `WHO_2022_VA_2026` was kept apart from `WHO_2022_VA` for ICD-10. Age/sex restrictions mirror the ICD-10 policy per VA cause. Exported in the CLI's policy JSON format as a draft the owner reviews, then checked in as `who_2022_icd11_mms_2026_01_policy_reviewed.json` under `docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/` next to the ICD-10 reviewed file. The reviewed file, not the generator, is authoritative. |
| D5 | same | Allowed. Existing assessments keep their `icd_classification` stamp; new coding and recodes use the current setting; reports show classification per record. |
| D6 | same | Already confirmed 2026-09-17; restate as closed, and add: the ICD-11 to VA bucket mapping is a separate scheme JSON (the ICD-11 counterpart of `WHO_2022_VA_2026`), never merged into an ICD-10 scheme, with the specific-beats-range rule applied when building it. |
| C1, C4 | `docs/policy/field-data-collection.md` | Deferred with the native app, not open: to be decided when that work starts. |
| Annex follow-up 1 (R10) | `.tasks/who-2026-annex-followups.md` | Confirmed by the clinical lead 2026-09-19: `R10` selectable, both sexes, all ages, bucket `VAs-06.01` in `WHO_2022_VA_2026`; the old `WHO_2022_VA` scheme keeps its own mapping. |
| Annex follow-up 3 (34 overrides) | same | Keep all 34 carried-forward overrides; document each in `docs/policy/who-2022-icd10-coding-allowability.md` with the annex value it departs from and the clinical lead as decider. No mapping change. |
| Annex follow-up 2 (full audit) | same | Yes, as part of the ICD-11 policy generator: it diffs the annex ICD-10 column against the reviewed policy and reports every code present in one and absent from the other, for the lead's review. Report only; no change without sign-off. |
| Annex follow-ups 4 to 7 | same | Engineering items, filed as beads issues in WP5: dev-versus-clone drift of the old scheme, tests for the two CLI commands and migration `c5f2a8d1e9b3`, current-state docs for the 2026 scheme, the "Selected ICD-10 Codes" label. |
| Translations delivery | new, 2026-09-19 | Translations are server data. Any frontend (the browser form now, the native app later) fetches a locale's translations from the server by `instrument_code`, `locale` and `version`, and picks up updates by revalidating the version; nothing is baked into the instrument bundle beyond `en`. |
| i18n method | new, 2026-09-19 | Translations use an industry-standard interchange format: XLIFF 2.0 export and import per locale, with stable resource ids (`question.<name>.label|hint|guidance_hint`, `choice.<list>.<name>.label`), source `en`, target per locale and per-unit state, so translators work in CAT tools. The workbook importer stays as the seeding path; storage and the JSON serving contract are unchanged. Where no translation exists the form shows English. |
| API first | new, 2026-09-19 | The code is API first and returns JSON only, so the UI can be decoupled or replaced. Every new or changed endpoint in WP1, WP2 and WP6 is a JSON API under `/admin/api` or `/api/v1`; the admin panels and the intake page are JavaScript clients of those endpoints and receive no new state through template context. |
| "unit-scoped listing refinements" | `docs/policy/web-intake.md` | Struck: no concrete item behind it; `list_deaths` already scopes by unit grants (`web_intake_service.py:400-425`). |

## Work packages, in order

### WP0. Save this plan into the repository (S, first action)

Copy this document to `docs/planning/web-capture-project-configuration-plan.md`
with the required front matter (`title`, `doc_type: plan`, `status: active`,
`owner: DigitVA Data Collection`, `last_updated: 2026-09-19`), commit it on
its own with the decisions table as the commit's substance, and link it
from `docs/planning/va-data-collection-plan.md` and `handoff.md`. Create the
beads issues for WP1 to WP6 in the same step with their dependency edges.
Move the nine downloaded workbooks' README (WP6) into this commit only if
the owner confirms they may be committed; otherwise the plan notes they are
untracked.

### WP1. Web form type and the two extensions become project settings (M)

**Goal.** A project names the form type its web form uses and switches the
two extensions; the web `va_forms` row and the form-options endpoint read
them, so a web-only project always has a default questionnaire.

**Schema, one additive migration chained on `f2a9c4d7e1b3`** (verify with
`flask db heads` before and after; no app imports; no data loss; downgrade
drops the columns). WP6 adds a second migration after it, so the chain
becomes `f2a9c4d7e1b3 -> WP1 -> WP6`:
- `va_project_master.web_intake_form_type_id` UUID nullable FK
  `mas_form_types.form_type_id`. Null means `WHO_2022_VA`, today's
  behaviour.
- `va_project_master.web_intake_intake_note` Text nullable. Null means the
  system default note (a module constant, not a stored default, so the
  wording can change without a migration). Empty string means no screen.
- `va_project_master.web_intake_death_summary_enabled` Boolean NOT NULL
  server_default true.
- `mas_form_types.base_instrument_code` String(32) nullable, backfilled in
  the same migration with `UPDATE ... SET base_instrument_code='WHO_2022_VA'
  WHERE form_type_code LIKE 'WHO_2022_VA%'` in plain SQL.

**Defaults for a new web project (decided 2026-09-19).** One constant,
`WEB_PROJECT_DEFAULTS` in `app/services/web_intake_service.py`, applied by
the project POST to any key the client omits whenever
`web_intake_mode != off`, and mirrored by the panel's create form:

| Setting | Default |
| --- | --- |
| `web_intake_form_type_id` | `WHO_2022_VA` |
| `web_intake_intake_note` | the system default welcome note (null) |
| `web_intake_death_summary_enabled` | true (all media uploads on) |
| `social_autopsy_enabled` | false (no social autopsy layer) |
| `web_intake_available_locales` | `["en", "hi"]` |
| `web_intake_narration_languages` | `["english", "hindi"]` |
| `coding_intake_mode` | `pick_and_choose` |

`hi` is accepted by the validator only when it is an active instrument
locale (WP6 makes that a table; today it is the registry in
`app/services/web_form_instruments.py`, which lists only `en`). WP1 lands
before WP6, so until WP6 lands the default is stored as intended, the
resolver serves `en` alone and the readiness `locales` check reports the
gap. Existing projects are not changed; the defaults apply on create.
Note `admin_create_project` today ignores `coding_intake_mode` and
`web_intake_mode` from the payload (pre-existing); WP1 makes the POST accept
both so the defaults can take effect on create.

**Files.**
- `app/models/va_project_master.py`, `app/models/va_field_mapping.py`
  (`MasFormTypes`): columns.
- `app/routes/api/organization.py`: `instrument_code_for()` becomes a lookup
  of `base_instrument_code` (accept a form type row or code; one query,
  cached per request only if it is called per row). `_project_form_types`
  unions the ODK mapping types with the types of the project's active
  `form_source='web'` `va_forms` rows, and includes the configured web form
  type when no web row exists yet; default is the configured web type when
  `web_intake_mode != off`, else the existing most-sites rule.
  `_enabled_extensions` emits `intake_screen` when the resolved note is
  non-empty and `death_summary` when the flag is on; the endpoint serves
  `intake_note` text alongside.
- `app/services/runtime_form_sync_service.py::ensure_web_runtime_form`:
  resolve the form type from the project column, falling back to
  `WHO_2022_VA`; raise on an inactive configured type. Existing web rows keep
  their `form_type_id`; the readiness check reports drift.
- `app/routes/admin.py`: `_serialize_project` and the shared project
  validator (`_web_intake_form_option_updates` pattern from `5b22094`)
  accept the three settings; the form type must be an active
  `mas_form_types` row with a non-null `base_instrument_code` and a
  confirmed PII set (reuse the confirmation helper behind
  `get_form_type_stats`); reject otherwise with a 400 naming
  `docs/policy/new-form-type-onboarding.md`. New
  `GET /admin/api/web-form-types` (admin) listing active types with
  `base_instrument_code` and `pii_confirmed`. Form-types admin panel and
  `flask form-types` show `base_instrument_code`; the form-type PUT accepts
  it.
- `app/templates/admin/panels/projects.html`: "Web form questionnaire"
  select (unconfirmed types disabled), "Welcome note" textarea with a
  "use default" affordance, "Death summary upload" switch defaulting on for
  new projects. Same read/write pattern as the language inputs.
- `app/templates/va_frontpages/va_intake_form.html`: render the welcome
  note above the form when `intake_screen` is enabled (a card with a
  "Start" button that reveals the host); nothing for `death_summary` until
  attachments phase 2, but the page must tolerate the extension name.

**Tests.**
- `tests/routes/test_form_options_api.py`: a project with no ODK mapping and
  `web_intake_mode=direct` serves one default form type with
  `instrument_code=WHO_2022_VA` (present first); a project configured with
  `WHO_2022_VA_SOCIAL` serves it as default; an ODK-mapped project without
  the setting keeps today's answer; `intake_screen` present with the default
  note, absent when the note is blanked; `death_summary` present by default,
  absent when switched off.
- `tests/services/test_web_intake_service.py`: `start_draft` on a project
  configured with the SOCIAL type creates a web form carrying that
  `form_type_id`; an inactive configured type is refused.
- Admin PUT/POST: accepts an active confirmed type; rejects inactive,
  unconfirmed, and a type with null `base_instrument_code`.
- `tests/test_admin_shell.py`: panel renders the three inputs and references
  `/admin/api/web-form-types`.
- Defaults: a POST with `web_intake_mode=direct` and no other web settings
  creates a project with every row of the defaults table (assert each
  value); a POST with `web_intake_mode=off` leaves the existing model
  defaults; an explicit value in the payload wins over the default;
  `coding_intake_mode` and `web_intake_mode` from the payload are honoured
  on create.
- `instrument_code_for` tests: reads the column; a code with the WHO prefix
  but null column (possible after the form-type PUT) returns null, proving
  the prefix rule is gone.
- `tests/migrations/test_schema_drift.py` and the no-app-imports guard.

**Docs.** Policy first, in the same commit: `docs/policy/web-intake.md`
(which form type a web form carries; the two extensions; W6 wording),
`docs/policy/va-web-form-options.md` (`form_types` derivation; the two
extension rows; `base_instrument_code` landed; Q6 closed),
`docs/policy/new-form-type-onboarding.md` (`base_instrument_code` step),
`docs/policy/va-form-project-configuration.md` (P2 closed). Then
`docs/current-state/data-model.md`.

### WP2. Web-capture readiness check (M)

**Goal.** One admin endpoint, one panel card and one CLI command that say
whether a project can capture through the web form and route, and what is
missing.

**Endpoint.** `GET /admin/api/projects/<project_id>/web-intake-readiness`,
`role_required("admin", "project_pi")`, PI limited to owned projects (same
pattern as the project-sites endpoints in `app/routes/admin.py` near line
1290). Returns `{"ready": bool, "checks": [{"code", "status": "ok|warn|fail",
"message", "fix_hint"}]}`. Logic in new
`app/services/web_intake_readiness_service.py`, pure reads:

| code | fail when | reuse |
| --- | --- | --- |
| `mode` | `web_intake_mode == off` | `web_intake_service.get_web_intake_mode` |
| `sites` | no active project site (web forms are per site) | query as in `ensure_web_forms_for_project` |
| `web_forms` | an active site lacks a web `va_forms` row; warn when a row's type differs from the project setting | `VaForms` |
| `form_type` | no default form type, null `base_instrument_code`, or PII set unconfirmed | `_project_form_types`, PII helper |
| `org_tree` | levels exist but no active unit at the deepest required level; warn when no tree (legacy routing) | `organization_service` |
| `geography_fields` | tree present but the bundled instrument lacks an `org_<level_code>_code` field for a level (warn) | `organization_service.odk_field_name_for_level`, instrument field list |
| `interviewers` | no active interviewer grant reaches the project; warn when only project-scoped grants exist in a tree project | `org_grant_service` |
| `coding_scope` | `coding_scope_level_id` set with intake mode not pick-and-choose | columns |
| `locales` | stored available locales contain codes the instrument lacks (warn) | `web_form_instruments.instrument_locales` |

**Panel.** "Web capture" badge per row in `projects.html` (`Ready` /
`n issues`), loaded lazily; the check list inside the edit form. **CLI.**
`flask web-intake readiness <project_id>` in `app/commands/`.

**Tests.** `tests/services/test_web_intake_readiness_service.py`: build a
project step by step, assert each check is reported failing, add the
setting, assert it clears, and `ready` is true at the end. Route test:
admin 200, PI on own project 200, PI on another 403, anonymous JSON 401;
`tests/test_route_auth_coverage.py` stays green.

**Docs.** Policy: "Ready for web capture" section in
`docs/policy/web-intake.md`. Then `docs/current-state/admin-and-setup.md`;
update `.tasks/org-model-administrator-explainer.md` (largely discharged).

### WP3. Routing confirmation end to end (S)

New `tests/routes/test_intake_org_routing_e2e.py`: two-level project, live
units A and B, project-scoped interviewer, coder scoped to B, coder scoped
to A, pick-and-choose with `coding_scope_level_id` at the leaf. Through the
HTTP client: register a death under B, start, save, submit. Assert (a)
`va_submissions.org_unit_id` is B, (b) the payload carries every
`org_<level_code>_code` on B's path, (c) the case is in the B coder's
`get_pick_available_forms()` (present first), (d) absent from A's. Reference
the deactivated-unit refusal at `tests/services/test_web_intake_service.py:557`
rather than duplicate it.

**Docs.** Strike the "unroutable case" row from Known defects in
`docs/planning/va-data-collection-plan.md` with the evidence; add "web
submissions route identically to ODK ones" to
`docs/current-state/health-system-organization-model.md`.

### WP4. Record every decision in the documents that raised it (S)

Docs only, one commit. For each row of the decisions table: replace the open
row or bullet with the decision and date, in the style the doc already uses
for resolved items (strikethrough plus "Resolved 2026-09-19"). Files:
`docs/planning/va-data-collection-plan.md` (Q6, C1 deferred, W6 pointer),
`docs/planning/who-va-2022-web-intake-plan.md` (W1 landed elsewhere, W6),
`docs/planning/icd11-coding-screen-integration-plan.md` and
`.tasks/icd11-coding-screen-integration.md` (D2, D3, D5, D6, with the note
that no curated file exists yet and the reviewed-file path),
`docs/policy/field-data-collection.md` (C1, C4 deferred with the app),
`docs/policy/web-intake.md` (strike "unit-scoped listing refinements").
Refresh `last_updated` everywhere touched. `tests/test_policy_docs.py`
must stay green (front matter). No open-question row remains anywhere
under `docs/` or `.tasks/` except those explicitly marked deferred-with-
native-app; grep for `| Q`, `| O`, `| W`, `| D`, `| C`, `| P` rows and
"open" markers to prove it, and record the grep in the commit message.

### WP5. Close the WHO 2026 annex follow-ups (S)

- Export the 34 carried-forward overrides from the live `WHO_2022_VA_2026`
  scheme against the annex CSV (`flask cod-buckets export` or a one-off
  read-only query over `map_icd_cod_buckets` joined to
  `who_2022_va_cause_list_icd10_icd11.csv`), and record each in
  `docs/policy/who-2022-icd10-coding-allowability.md` in a table: code,
  bucket kept, annex bucket, decided by the clinical lead 2026-09-19.
- Mark follow-up 1 confirmed and follow-up 3 documented in
  `.tasks/who-2026-annex-followups.md`; move follow-up 2 into the ICD-11
  generator beads issue; file follow-ups 4 to 7 as four beads issues.
- `docs/current-state/cli-reference.md` and the data-model doc gain the two
  2026 CLI commands and the scheme (follow-up 6 is small enough to do here).
- Tests: `tests/test_policy_docs.py` stays green; a test asserts the policy
  doc's override table lists exactly the codes whose live bucket differs from
  the annex (present-before-absent: assert the table has rows, then that no
  differing code is missing from it).

### WP6. Instrument translations: stored, managed, editable (L)

**Decision (owner, 2026-09-19).** Translations are data, not part of the
bundle: they live in a table, are seeded from one documented source form
per language, and an admin can add a language, import a workbook, and edit
any string. The instrument's structure stays pre-built and immutable
(decision O1); a translation changes only the text shown for a question,
hint, guidance note or choice, and the translation version used is recorded
on every submission so what the respondent saw remains reconstructible.

**Sources.** Nine deployed ODK form definitions the owner downloaded into
`docs/kb/WHO_VA_2022_Docs/` (untracked as of 2026-09-19; commit them as
reference material with a README per decision E8). Verified by reading the
workbooks:

| Locale | Language | Source workbook | Cross-check workbooks |
| --- | --- | --- | --- |
| `hi` | Hindi | `RJ01_ICMRVA_WHOVA2022.xlsx` | `KA01_DS`, `KEM_VAADU` |
| `ta` | Tamil | `JIPMER_DS_WHOVA2022.xlsx` | `PY01_ICMRVA` |
| `kn` | Kannada | `KA01_DS_WHOVA2022.xlsx` | |
| `mr` | Marathi | `KEM_VAADU_WHOVA2022.xlsx` | `KA01_DS` |
| `ml` | Malayalam | `KL01_DS_WHOVA2022.xlsx` | |
| `kha` | Khasi | `ML01_ICMRVA_WHOVA2022.xlsx` | |
| `or` | Odia | `OD01_ICMRVA_WHOVA2022.xlsx` | |
| `bn` | Bangla | `TR01_DS_WHOVA2022.xlsx` | |
| `fr` | French | `whova2022_xls_form_for_odk.xlsx` (reference) | |

Rule: **exactly one source form per language, documented.** The table goes
into `docs/policy/va-form-project-configuration.md` under "Translation
sources" (language, locale code, source workbook, project, ODK form id,
download date, who assigned it). The importer refuses a workbook that is
not the documented source for that locale unless run with an explicit
cross-check flag, in which case it only reports differences. Changing a
language's source is a policy change: edit the doc first.

> **Superseded 2026-09-20.** The enforcement described in this paragraph was
> removed: the importer no longer reads the "Translation sources" table and
> accepts any readable workbook for any locale. The table remains as
> provenance for humans. The cross-check flag survives as a plain dry run.
> The decision and its reason are recorded in
> `docs/policy/va-form-project-configuration.md` ("Translation sources").
> The rest of this paragraph -- translations as data, seeded from a workbook,
> editable per string -- still holds. Instrument
locale codes are a separate axis from `mas_languages` codes (`kha` versus
`khasi`); nothing maps between them.

**Schema, one additive migration** (chained after WP1's; no data loss):
- `mas_instrument_locales`: `instrument_code`, `locale_code`, `language_name`,
  `is_active` (default false until coverage passes), `source_document`,
  `source_sha256`, `imported_at`, `version` (integer, bumped on every edit
  or import), `updated_at`. Primary key `(instrument_code, locale_code)`.
- `map_instrument_translations`: `instrument_code`, `locale_code`,
  `item_kind` (`question` | `choice`), `item_key` (question `name`, or
  `list_name` + `/` + choice `name`), `field` (`label` | `hint` |
  `guidance_hint`), `text`, `source` (`imported` | `edited`), `updated_by`,
  `updated_at`. Unique on the five key columns. Sized for roughly 2,000
  strings per locale.
- `va_web_intake_drafts.meta` (JSONB, exists) records
  `{"locale": "hi", "translation_version": 7}` at start and at every locale
  switch; `build_web_payload` copies it into the payload so the submission
  carries it (`payload["intake_locale"]`, `payload["intake_translation_version"]`).

**Importer.** `flask instrument-translations import <instrument_code> <locale>
<workbook>`: uses `xlsform_instrument_builder._language_columns` to find the
`label::Name (code)` / `hint::` / `guidance_hint::` columns, merges by
question `name` and by `list_name` + `name` for choices, splits cells that
pack English and the target language on a newline (seen in RJ01:
"VA interviewer\nवीए साक्षात्कारकर्ता") when the English half equals the
reference text, reports every reference item the workbook lacks and every
workbook item the reference lacks, and never creates a question. Idempotent
upsert; `source='imported'` rows are overwritten on re-import, `edited` rows
are kept and listed. `export` writes the same JSON the panel uses. A locale
is activated when coverage of survey labels is at or above a threshold the
owner sets (recommend 95 percent); the command prints coverage and refuses
activation below it unless `--force`, which is logged.

**Serving.** `GET /api/v1/instruments/<instrument_code>/translations/<locale>`
(`login_required`, cacheable by `version`, ETag) returns
`{"version", "questions": {name: {label, hint, guidance_hint}}, "choices": {list/name: {label}}}`.
This is the one delivery contract for every frontend: the browser form
today, the native app later. A client caches a locale by `version`,
revalidates against `translation_versions` in the form-options payload (or
the ETag) whenever it loads a form, and re-fetches only when the version
moved, so an admin's edit reaches interviewers on their next form without
a rebuild or a redeploy. The intake page applies it client-side after
loading the pre-built instrument: a small pure function in `app/static/js/intake/` (WP2 of the
consolidated plan's JS extraction can be done here for this file only)
walks the instrument's sections, questions and choice lists and sets
`label[locale]`, `hint[locale]`, `guidance[locale]` from the map, then
assigns `el.instrument` and `el.setAttribute("locale", ...)`. Switching
locale in the picker re-fetches and re-applies. The registry
`INSTRUMENT_LOCALES` in `app/services/web_form_instruments.py` becomes a
query over active `mas_instrument_locales` rows (keep `en` as the base
locale that always exists and needs no rows); the registry-versus-bundle
test now asserts only that `en` is in the bundle. `_resolve_locales` and the
admin validator read the same query. The form-options payload adds
`translation_versions: {locale: version}` so an open page can revalidate.

**Admin panel.** New `app/templates/admin/panels/instrument_translations.html`
and routes in a new `app/routes/admin_translations.py` (`role_required("admin")`):
list locales with coverage, version, source document and active flag;
import a workbook (multipart, size limit, xlsx only, CSRF); activate or
deactivate a locale; open a locale and edit strings inline (search by
question name or English text, shows the English reference alongside, saves
one string per PUT, marks `edited`, bumps the locale version); export JSON.
Every edit writes the activity log with the item key and the old and new
text.

**Tests.**
- `tests/services/test_instrument_translation_import.py`: a two-question
  reference plus a workbook with one Hindi label yields one row and a report
  naming the other (present first, then the gap); packed cells split; a
  workbook cannot add a question; re-import overwrites `imported` rows and
  keeps `edited` ones; coverage gate activates or refuses; the documented
  source rule refuses an undocumented workbook.
- A slow test over the real workbooks asserts each documented locale reaches
  the threshold, so a re-downloaded workbook cannot silently drop a language.
- `tests/routes/test_instrument_translations_api.py`: auth matrix for the
  serving endpoint and the admin routes; ETag revalidation; an edit bumps
  the version; an inactive locale is not served to the form.
- `tests/routes/test_form_options_api.py`: available locales come from
  active locale rows; a project listing `hi` serves it once `hi` is active
  and not before (present-before-absent in that order).
- `tests/services/test_web_intake_service.py`: the draft records locale and
  translation version; the payload carries them.
- jsdom: the client-side apply function sets Hindi labels on the instrument
  copy and leaves English untouched; switching locale re-applies.

**Docs.** Policy first: `docs/policy/va-form-project-configuration.md`
("Translation sources" table and the one-source-per-language rule; what a
translation may change and what it may not), `docs/policy/va-web-form-options.md`
("Adding a language" becomes: import the documented source form, reach the
coverage threshold, activate; `uiTranslations` remains separate), and a new
`docs/policy/instrument-translations.md` if the two grow past a page. Then
`docs/current-state/data-model.md`, `admin-and-setup.md`, `cli-reference.md`.

**Depends on.** WP1 (the validator reads the locale query). Independent of
WP2 to WP5; WP2's `locales` check reads the active-locale query.

### Deferred, filed as beads issues, not done here

- ICD-11 phases 3 to 6 and the project ICD classification default (decisions
  now recorded; separate plan).
- The generated ICD-11 policy draft for the owner's review (D3).
- Attachments phase 2 (renders `death_summary`; carries W6), validator
  sidecar W1, native app (C1, C4).

## Order and dependencies

WP0 first, then WP1. WP3, WP4, WP5 and WP6 are independent of WP1 and run in
parallel with it (WP6's defaults only become servable once WP1 is in). WP2
last (its `form_type` and `locales` checks read WP1's and WP6's output). Each WP is its own
commit; policy docs change in the same commit as the behaviour, before it in
the narrative; current-state docs after.

## Verification

- Targets per WP, then the full suite, one runner, own database:
  `docker compose exec -T -e TEST_DATABASE_URL=postgresql://minerva:minerva@minerva_db_service:5432/minerva_test_pii minerva_app_service uv run --no-sync python -m pytest tests -q -p no:cacheprovider`
  Baseline to beat: 1,469 passed.
- `flask db heads` before and after each of the two migrations (WP1, WP6);
  single head. Empty database replay of the whole chain per
  `docs/policy/test-harness.md` rule 2, reaching the new head with the four
  WP1 columns, the backfilled `base_instrument_code`, and the two WP6
  tables.
- Panel JS: exercise `projects.html` and the translations panel in the
  session's jsdom harness (scratchpad `panel_test2.js` pattern); the
  client-side translation apply function gets a checked-in jsdom test under
  `tooling/who-va-2022` (`node --test`), the first JS test in the repo.
- Manual on the dev database: set a project to `direct` with no ODK
  mapping, confirm `/api/v1/organization/<id>/form-options` serves a default
  form type and the welcome note, and the readiness endpoint reports `ready`
  once sites, tree and an interviewer grant exist.
- Bookkeeping per CLAUDE.md: `bd create` one issue per WP before code with
  dependency edges (WP2 after WP1), claim and close as they land,
  `bd remember` the D3 finding (no curated file exists), update
  `handoff.md` (migration chain, test count, decisions table, what is
  next), `git pull --rebase && git push`.
