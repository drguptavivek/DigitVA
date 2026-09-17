---
title: WHO VA 2022 Web Intake — Integrating the who-2022-va Questionnaire Package
doc_type: planning
status: proposed
owner: engineering
last_updated: 2026-09-18
---

# WHO VA 2022 Web Intake — Integrating the who-2022-va Questionnaire Package

## Requirement (as stated 2026-09-17)

Let field workers (CHOs and others with `can_fill_va_form` at their unit)
fill the WHO 2022 verbal autopsy questionnaire in a DigitVA web page instead
of ODK Collect, using the questionnaire package at
`https://github.com/aashieshsingh/WHO-va-2022` (npm `@drguptavivek/who-2022-va`),
with submissions routed to the right organization unit by the standard
`org_<level>_code` fields.

## What the package provides (verified 2026-09-17 from its README, docs and npm)

- npm `@drguptavivek/who-2022-va` 0.1.0 (published 2026-07-18), MIT; WHO
  questionnaire content CC BY-ND 3.0 IGO. ESM only, no CommonJS, no UMD, no
  prebuilt browser bundle, no CSS file (styles injected at runtime). Optional
  peer dependencies react and react-dom; direct dependency pdfjs-dist.
- Entry points: headless (`whoVa2022Instrument`, `validateSubmission`,
  `applyCalculations`), `/web` React component, `/web-component` custom
  element `<who-va-2022-form>`, `/native` for Expo.
- One canonical JSON instrument (`va_who_2022`, instrument version
  `2023072701`, form version `2022`); 450 questions, 38 calculated fields;
  the XLSForm is reference only. One non-WHO field:
  `custom_medical_certificate_upload`.
- Answers use canonical WHO ids (`Id10019`), choice values not labels, ISO
  dates. Irrelevant and undeclared fields are stripped on normalization.
- Web component: properties `draftStore`, `platform`, `draft-id`, `locale`;
  methods `getData/setData/validate/complete`; events `who-va-change`,
  `who-va-validation`, `who-va-draft-saved`, `who-va-draft-error`,
  `who-va-complete` with `{data, formVersion, instrumentId, instrumentVersion,
  valid, issues}`.
- Prefill: `createWhoVaInitialDataFromPrefill()` maps interviewer (`Id10010*`),
  deceased (`Id10017/18/19/21/23/24/52`), location (`Id10057`), and the
  HIV/malaria presets (`Id10002/3`).
- Drafts: host-injected `WhoVaDraftStore`; media are durable references, the
  host uploads blobs (`loadWhoVaWebAttachmentBlob`) via FormData.
- No server submission API and no ODK Central integration. Server-side
  validation is expected to call `validateSubmission()` (JavaScript).

## What DigitVA needs from an intake path (verified in code)

- A submission row needs `va_form_id` (`va_forms`), a `va_sid`, submission
  date, data collector, consent (`Id10013`), narration language
  (`narr_language`/`language`), deceased age and sex, and the derived
  summary/category fields, all computed by
  `_submission_projection_fields` in
  `app/services/va_data_sync/va_data_sync_01_odkcentral.py` from a flat payload
  keyed by leaf field names.
- The payload becomes an active `va_submission_payload_versions` row through
  `ensure_active_payload_version`; workflow entry is
  `route_synced_submission` (consent valid -> `attachment_sync_pending`) then
  `mark_attachment_sync_completed` -> `smartva_pending`, after which SmartVA,
  coding and reporting proceed unchanged.
- DigitVA's ODK form carries 56 non-WHO fields that the package's instrument
  does not: `language`, `Site`, `unique_id`, `site_individual_id`,
  `survey_state`, `survey_district`, `narr_language`, `comment`, the
  age helpers (`isNeonatal`, `isChild`, `isAdult`, `ageInDays`, `ageInYears`,
  `ageInMonths`, `age_group`, ...) and the media slots (`imagenarr`,
  `md_im1..30`, `ds_im1..5`). Which of the age helpers the package computes
  under the same names is unverified (spike item).
- Rule 8 of AGENTS.md makes ODK the source of truth for **synced**
  submissions. Web submissions are a second source and must be invisible to
  ODK sync: enumeration, delta checks and `missing_in_odk` retirement must be
  scoped to ODK-mapped forms.
- Attachments have a store-first lifecycle in `app/services/attachment_service.py`
  (`generate_storage_name`, `new_ingest_temp_path`, `_store_write`,
  source/derivative/store states), which a web upload can enter directly.
- The front end is Jinja, jQuery, Bootstrap and HTMX with vendored assets under
  `app/static/vendors`; there is no JavaScript bundler in the repo.

## Requirements added 2026-09-18

- **Vendoring route.** The package source is copied into `vendor/who-va-2022/`
  (no submodule, no npm dependency) and modified in place; DigitVA's extra
  questions live in `vendor/who-va-2022/src/digitva-extension.ts` and are
  composed into the instrument by `src/instrument.ts`. `tooling/who-va-2022/`
  bundles it into `app/static/vendor/who-va-2022/who-va-2022.web-component.js`
  (committed, with `manifest.json` carrying version, size and sha256).
  Upstream fixes are merged by hand.
- **Death register first.** Besides direct form entry, a project may register a
  death first (deceased basics, unit, date, informant) and start the VA from
  that entry, prefilled. A project setting `web_intake_mode` selects `off`,
  `direct`, `death_register` or `both`.
- **Unique id.** A PostgreSQL sequence assigns the human-readable id when the
  death is registered (or, in direct mode, when the draft is first saved), so
  it can be written on paper; the submission keeps a UUID internally. Format
  `<unit_code>-<zero-padded sequence>`; gaps are accepted.
- **Fields the interviewer answers** beyond WHO: `narr_language` (values are
  DigitVA's language codes), `imagenarr`, `md_count` + `md_im1..30`,
  `ds_count` + `ds_im1..5` (count-driven relevance as in the ODK form). The
  WHO instrument already has `comment`. Everything else DigitVA-specific is
  injected server-side.
- **Mobile performance risk.** The field lead reports the package's web form
  was slow on mobile devices. The bundle carries React, react-native-web and
  pdfjs (1.0 MB, 197 KB gzipped) and recalculates 38 fields on every change.
  Profiling on a low-end Android device with CPU throttling is a phase 1 task
  before rollout; candidate fixes are lazy section rendering, debounced
  recalculation, and dropping pdfjs from the default bundle.

## Proposed design

### 1. Delivery of the questionnaire

- Vendor a built browser bundle of the `/web-component` entry under
  `app/static/vendor/who-va-2022/<version>/` (built once with a small
  `tooling/who-va-2022/` Vite or esbuild project that pins the npm version and
  bundles React if the entry does not already include it). No CDN: coders and
  CHOs may be on restricted networks, and versions must be pinned.
- A Jinja page `/intake/new` (and `/intake/drafts/<id>`) hosts
  `<who-va-2022-form>`, sets `draftStore` to a DigitVA-backed adapter and
  `platform` services for date picking, audio recording and image capture.

### 2. Server side

- New blueprint `intake` (`app/routes/intake.py`, service
  `app/services/web_intake_service.py`): draft save/load/list, submit,
  attachment upload. CSRF via `X-CSRFToken`; JSON contracts so a future
  native app can reuse them.
- Drafts: table `va_web_intake_drafts` (id, user, project, org unit, JSON
  envelope, instrument/form versions, updated_at); private to the author.
- Submission: `POST /intake/api/submissions` with the completion payload.
  Server re-validates with the package's own `validateSubmission()` in a
  small Node validator service (`who_va_validator_service` in compose, one
  HTTP endpoint, same pinned package version). The Flask side adds the
  DigitVA-specific fields (see §3), builds the flat payload, creates the
  `va_submissions` row and payload version, and routes the workflow exactly
  as sync does, then records the audit log entry.
- Identity: `va_sid = web-<uuid>-<form_id lower>`, `va_instance_name` from the
  same rule ODK uses, `va_data_collector` = the logged-in user's name,
  `va_uniqueid_real` generated as `<unit_code>_<yyyymmdd>_<seq>` (format to
  confirm against the ODK `unique_id` convention).
- Attachments: `POST /intake/api/submissions/<sid>/attachments` streams each
  blob to the store through the existing attachment lifecycle, names it after
  the media slot it fills (`imagenarr`, `md_im1`, ...), and when all expected
  attachments are stored calls `mark_attachment_sync_completed`.
- A virtual form per project-site: a `va_forms` row with
  `odk_form_id = WEB_WHOVA2022`, `form_type = WHO_2022_VA`, and a new
  `form_source` column (`odk` | `web`, default `odk`). ODK sync enumerates
  `map_project_site_odk`, so web forms are never synced; the `missing_in_odk`
  retirement and any ODK write-back must additionally filter on
  `form_source = 'odk'`.

### 3. Field contract between the package and DigitVA

- WHO ids pass through unchanged.
- DigitVA-specific fields are supplied server-side from context, never typed
  by the interviewer: `Site`, `survey_state`, `survey_district` and the
  `org_<level>_code` fields from the interviewer's unit and its ancestors;
  `unique_id`, `site_individual_id` generated; `language`/`narr_language`
  from the page locale and the narration language choice; `comment` from an
  optional envelope note.
- Age helpers: if the package's calculated fields do not emit them under
  DigitVA's names, compute them in Python from `Id10021/Id10023/age_*`
  using `normalize_who_2022_age` (spike decides).
- Media slots: the package keeps media as references; the server maps them to
  DigitVA's slot names in the payload so the coding screen and SmartVA
  preparation keep working.
- Consent (`Id10013`), narrative (`Id10476`) and all skip logic are the
  package's; nothing is re-implemented.

### 4. Access

- New grant role `interviewer` (fill VA forms) with `project_site` scope
  now and `org_unit` scope once organization phase 2 lands; cadre gating
  through `can_fill_va_form`. Landing page `intake`.
- Interviewers see only their own drafts and their own submitted cases
  (status only); data managers see web submissions like any other.

### 5. Out of scope for the first release

- Editing a submitted web case (ODK cases use Enketo; a web edit needs a
  payload-version-aware flow).
- Offline PWA and the Expo native app (the package supports both; the same
  intake API serves them later).
- Multilingual questionnaire text beyond English (package ships `en` only;
  Hindi and others need language files).

## Decisions to confirm

| # | Question | Recommendation |
|---|---|---|
| W1 | Server-side validation | Node validator sidecar running the package's `validateSubmission()`; Python does structural checks only. Avoids porting 450 questions of skip logic. |
| W2 | Asset delivery | **Decided:** vendored source copy plus committed bundle under `app/static/vendor`, no CDN. |
| W3 | Who may fill forms | New `interviewer` role, cadre-gated, unit-scoped when available. |
| W4 | Virtual form granularity | One web form per project-site (container site for tree projects); routing to units happens by the code fields, as for ODK. |
| W5 | Unique id format | **Decided:** PostgreSQL sequence, `<unit_code>-<seq>`, assigned at death registration or first draft save; UUID internally. |
| W6 | Mandatory media | Same as the ODK form today (audio narration expected); confirm with the field lead. |

## Spike results (2026-09-18, run on the host with Node 24 in a scratch project)

1. **Bundle.** `esbuild` on the `/web-component` entry needs `react`,
   `react-dom` and `react-native-web` installed (the entry imports all
   three; none are bundled by the package). Output as a single minified ESM
   file: 1.38 MB raw, 314 KB gzipped, with pdfjs included. Fit for vendoring
   under `app/static/vendor/who-va-2022/0.1.0/`; the build recipe goes into
   `tooling/who-va-2022/` with pinned versions.
2. **Field contract.** The instrument has 450 questions, 38 calculated. All
   372 WHO ids that DigitVA maps exist in the package under the same names,
   including every age helper DigitVA reads (`isNeonatal`, `isChild`,
   `isAdult`, `ageInDays`, `ageInDays2`, `ageInYears`, `ageInYears2`,
   `ageInMonths`, `age_group`, `age_neonate_days`, `age_neonate_hours`). The
   42 DigitVA fields absent from the package are exactly the ones §3 supplies
   server-side: `Site`, `unique_id`, `site_individual_id`, `survey_state`,
   `survey_district`, `narr_language`, `imagenarr`, `md_im1..30`,
   `ds_im1..5`. No Python re-computation of age helpers is needed. The
   package also carries 82 ids DigitVA does not map (sub-fields such as
   `Id10023_a/_b`, unit selectors, `custom_medical_certificate_upload`,
   `audit`); they pass through into the payload unharmed.
3. **Validation.** `validateSubmission()` returns `{valid, data, issues}` in
   0.2 ms per call after a 2 ms first call; a Node validator sidecar is
   cheap. Issues carry `question`, `code`, `message`. (The version fields the
   docs mention are not on the 0.1.0 result object; the sidecar adds them
   from the instrument constants.)
4. **Still to confirm in phase 1:** the category display service and SmartVA
   preparation on a web payload (expected to work since names match), and the
   ODK `unique_id` convention for W5.

## Phases

1. Spike results recorded here; `form_source` column and virtual web form;
   intake page with drafts and submission without media; workflow routing;
   sync scoping tests.
2. Attachments (audio, images, certificate) through the store; SmartVA and
   coding on a web case end to end.
3. `interviewer` role, cadre gating, org-unit prefill and `org_<level>_code`
   population; interviewer dashboard.
4. Offline PWA; native app via the package's `/native` entry.

## Verification

Unit tests for the payload builder (field contract, age helpers, media slot
mapping), route tests for authorization and CSRF, an end-to-end test that a
web submission reaches `ready_for_coding` and appears in pick-and-choose,
and sync tests proving web forms are never enumerated or retired by ODK sync.

## References

- Package: `https://github.com/aashieshsingh/WHO-va-2022`
- `app/services/va_data_sync/va_data_sync_01_odkcentral.py` (projection, creation, routing)
- `app/services/submission_payload_version_service.py`, `app/services/workflow/transitions.py`
- `app/services/attachment_service.py`, `docs/policy/attachment-storage.md`
- `docs/planning/health-system-organization-model-plan.md` (routing by unit codes)
- `docs/policy/odk-retired-submissions.md`, `docs/policy/odk-sync-policy.md`
