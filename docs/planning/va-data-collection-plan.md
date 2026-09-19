---
title: VA Data Collection — Consolidated Plan (engine, form pipeline, clients)
doc_type: planning
status: active
owner: engineering
last_updated: 2026-09-19
---

# VA Data Collection — Consolidated Plan

## Why this document

DigitVA is growing a second way to collect verbal autopsies, alongside ODK
Central. The work has been running across three planning documents, two policy
documents and a long working session, and the sequencing in
[`who-va-2022-web-intake-plan.md`](who-va-2022-web-intake-plan.md) now predates
several decisions that replaced it — it still lists an offline PWA, which is
ruled out.

This is the single place for **scope, decisions and sequencing**. Detail stays
in the documents referenced at the end; where they disagree with this one, this
one is current.

## Scope

Collecting the WHO VA 2022 questionnaire — and later PHMRC and the Ballabgarh
form — in DigitVA's own clients, and landing those submissions in the same
workflow ODK-synced cases use. Out of scope: changing how ODK Central
collection works, and the coding/reviewing workflow downstream of intake.

## The shape, in one page

**Four layers, each with one owner.**

1. **Authoring** — every questionnaire is an ODK XLSForm. One workbook serves
   both paths: published to ODK Central for ODK collection, and converted for
   DigitVA's clients. There is no second definition to keep in step.
2. **Conversion** — `app/services/xlsform_instrument_builder.py` turns a
   workbook into an instrument. DigitVA's `form_type_code` is supplied by the
   caller and is the key that field and choice mappings bind to; the XLSForm
   `settings` sheet (`form_id`, `version`) is recorded as provenance only,
   because it is author-controlled and changes on republish.
3. **Engine** — `vendor/who-va-2022`. This is **DigitVA's engine**, not a
   mirror of an upstream package: the vendored copy is the source, free to be
   restructured to suit this project, with no obligation to stay mergeable with
   anything outside. It evaluates ODK's expression language, so relevance,
   constraints and calculations pass through conversion untouched.
4. **Clients** — two, and only two (see
   [Field Data Collection Policy](../policy/field-data-collection.md)):
   - **Online browser intake.** Server-backed drafts; nothing persisted on the
     device. Exists and works.
   - **Native app, encrypted at rest.** For offline field work. Not started.

   A PWA is excluded: browser storage cannot hold keys in hardware-backed
   storage, and on iOS it can be evicted while holding the only copy of an
   interview.

**The server contract is Flask.** The Node validator is an internal callee, not
a front door — it holds no session, no database handle and no secrets. Drafts
are never validated (a draft is incomplete by definition); submissions always
are.

## Decision register

Earlier decisions stay in their own documents (W1–W6 in the web-intake plan,
O1–O8 in the organization plan, C1–C4 in the collection policy). These are the
ones taken while consolidating, which cut across all of them.

**W6 (mandatory media), resolved 2026-09-19:** no media is mandatory; audio
narration is encouraged; a typed narrative is wanted; medical papers,
discharge summaries and prior death certificates are uploaded as available.
Mandatory-media rules, if ever, are project configuration added with
attachments phase 2. See
[`who-va-2022-web-intake-plan.md`](who-va-2022-web-intake-plan.md#decisions-to-confirm)
for the full record.

| # | Decision | Date | Rationale |
|---|---|---|---|
| E1 | DigitVA keeps its own engine (`vendor/who-va-2022`) rather than adopting ODK Central's `@getodk/xforms-engine` | 2026-09-18 | It is ours to extend, it already has drafts, attachments and a React Native path, and phase 1 ships against it. ODK's engine covers more of the spec but has no offline drafts or audio capture, and needs a DOM. |
| E2 | Extend the engine for the ODK types the forms need rather than refusing them | 2026-09-18 | decimal, time, datetime, barcode, range, geopoint are basic field types; WHO forms may use them. |
| E3 | The converter refuses what the engine cannot render, by name | 2026-09-18 | Mapping a decimal onto an integer or a geopoint onto text discards what the interviewer entered and only surfaces downstream. |
| E4 | `formTypeCode` is the mapping key; the XLSForm `settings` sheet is audit only | 2026-09-18 | `form_id`/`version` belong to the form author and change on republish; binding mappings to them would silently re-point a project's mappings. |
| E5 | Repeats and entities are out of scope | 2026-09-18 | The forms are simple and use neither. Revisit only if a form needs them. |
| E6 | Alternative calendars and `image-map` are out of scope | 2026-09-18 | Six calendar systems, none used in the deployments planned. |
| E7 | Instruments are **built offline from one curated reference form per form type**, never converted at request time | 2026-09-18 | Conversion output needs review before it faces an interviewer, and there is no single workbook to convert automatically — see the per-site variance below. |
| E8 | Reference material comes from **ODK Central's deployed definitions**, not the generic WHO workbook | 2026-09-18 | `GET projects/{id}/forms/{id}.xlsx` returns what is actually in the field, already carrying DigitVA's extension fields. The generic workbook's placeholder choices ("Language 2", "Language 3") are exactly what must not reach an interviewer. |
| E9 | **Language lists are configuration, not part of the instrument.** The language question's choices are supplied from DigitVA's language data at composition time; `DIGITVA_NARRATION_LANGUAGES` is removed from the engine | 2026-09-18 | The hardcoded list matches WHO_2022_VA and is wrong for WHO_2022_VA_SOCIAL, and every site's workbook carries a different list. Baking one into either the engine or an instrument cannot be right for all of them. |


> **2026-09-19:** the project-configuration slice (web form type, extensions, defaults, readiness, translations) and the register of every decision taken that day are in `docs/planning/web-capture-project-configuration-plan.md`.

## Where we are

Verified means it was exercised, not merely written.

### Working and verified

- **Web intake phase 1** — death register, server-backed drafts with per-section
  saves, submission into the workflow through the same projection ODK sync
  uses. 41 tests.
- **The questionnaire page renders.** First browser run this session.
- **Engine type coverage** — decimal, time, datetime, barcode, range, geopoint,
  plus phonenumber/email/hidden metadata. Verified functionally through the
  built validator bundle (19 checks).
- **Appearances** — parser plus `numbers`, `masked`, `multiline`,
  `thousands-sep`, `month-year`, `year`, `search`, `columns`, `columns-n`,
  `columns-pack`, `no-buttons`, `likert`, `picker`, `rating`, `draw`,
  `signature`.
- **Inline markup** — labels, hints, guidance and choice labels render ODK's
  markdown/HTML subset instead of having it stripped. 17 tests; confirmed in a
  browser.
- **XLSForm converter** — conformance measured against the hand-audited WHO
  instrument: 30 differences remain, each one the package departing from its
  own workbook, recorded in the test.
- **Instrument identity** — `formTypeCode` + `source`; the web component takes
  a host-supplied `instrument` and reports `instrumentIdentity`. A converted
  workbook renders through the element.
- **Draft saving** — a failed save no longer stops all later saves; writes cut
  from one per keystroke to roughly one per pause.
- **PII field registry** — the `is_pii` flag is reproducible and covers the
  identifiers that were never flagged (`Id10073`, ABHA).

### Built but not wired

- **Node validator service** (`tooling/who-va-2022/validator-server.mjs`) — no
  compose service, no Python client. `submit_draft` still trusts the client's
  `valid`.
- **Vite dev config** for the questionnaire front end — unused.

### Not started

- Attachments on the web path (upload endpoint, platform adapters).
- The native app.
- PHMRC and Ballabgarh workbooks.

### Known defects

| | Where | Note |
|---|---|---|
| Submission with attachments never leaves `attachment_sync_pending` | `web_intake_service.submit_draft` | Latent: masked while no platform services exist. Must be fixed in the same change that enables attachments. |
| Engine test suite: 13 stale failures | `vendor/who-va-2022/tests` | Expectations predate the vendored extension. [Task](../../.tasks/who-va-engine-test-suite-stale.md) |
| Engine test suite is flaky | `web-validation-navigation` | One intermittent failure across full runs; passes in isolation. |
| ~~A project-scoped interviewer produces an unattributable case~~ | `web_intake_service._require_scope` | **Resolved 2026-09-19:** `_require_scope` in `app/services/web_intake_service.py` (lines 235-279) now requires a unit in any tree project; `tests/services/test_web_intake_service.py` (lines ~590-644) cover it. An end-to-end routing test lands as WP3 (`tests/routes/test_intake_org_routing_e2e.py`). |
| A converted instrument lacks DigitVA's extension fields | converter output | Language choices render as the workbook's placeholders. Either author those fields into each XLSForm or compose them after conversion. |

### Evidence for E7–E9 (measured 2026-09-18)

Both deployed forms were pulled from the live connection and converted:

| | WHO_2022_VA (`NC01_DS_WHOVA2022`) | WHO_2022_VA_SOCIAL (`va_who_2022`) |
|---|---|---|
| questions / sections | 507 / 33 | 522 / 35 |
| source version | `NC01_DS_WHOVA2022_20250726` | `KEM_VAADU_WHOVA2022_V2.2` |
| `language` choices | english, hindi | english, hindi, marathi |
| `narr_language` | english, hindi | absent |
| DigitVA extension fields | unique_id, Site, imagenarr, md_im1, ds_im1, survey_state | unique_id, Site, imagenarr, md_im1 |

Three things follow. **Deployed forms vary by site**: NC01 offers two languages
while `mas_choice_mappings` for the same form type lists six, because those
mappings accumulate across every site's form. **The forms are not
interchangeable**: one carries `narr_language`, `ds_im1` and `survey_state`;
the other does not. And **conversion succeeds on real workbooks** — 507 and 522
questions, no refused types — so the pipeline holds outside the WHO reference
workbook.

Consequence for the build step: choosing the reference form is a curation
decision per form type, recorded with the artifact, and the language question
is re-sourced afterwards rather than inherited from whichever site's workbook
was used.

### Base and extensions

The WHO 2022 instrument is the **base, and it is a subset**: 449 questions,
unmodified. Everything DigitVA and its projects collect beyond that is an
**extension layered on top** — which is how the engine is already built
(`src/generated/who-va-2022.instrument.json` plus `digitva-extension.ts`,
composed in `src/instrument.ts`). A deployed form is therefore the base plus
whichever extensions that deployment adopted, not a standard in its own right.

Measured across the deployed forms, the extensions stack like this:

| Layer | Adds | Seen in |
|---|---|---|
| WHO 2022 base | 449 questions | all |
| DigitVA core | `unique_id`, `Site`, `imagenarr`, `md_count` + `md_im1..30`, `comment` | all |
| Social autopsy | the social-autopsy sections | KEM_VAADU, ICMRVA, NC01_TVA |
| Intake screen + geography | `introduction`, `instructions`, `confirm_inst`, `survey_state`, `survey_district`, `survey_block`, `site_individual_id`, `narr_language` | ICMRVA |
| Death summary | `ds_available`, `ds_count`, `ds_im1..5` | ICMRVA, NC01_DS |

KEM_VAADU is the closest to plain WHO of the social-autopsy forms; the ICMRVA
family is the richest. `NC01_TVA` sits between them. A new deployment picks
layers; it does not pick a whole form.

### DigitVA VA extensions (target design)

Those layers become **named extensions** — reusable modules that any VA form in
the web clients can adopt, and that a project turns on in its own settings.
Observed in the deployed forms, they factor as:

| Extension | Questions | Notes |
|---|---|---|
| `digitva_core` | `unique_id`, `Site`, `imagenarr`, `md_count` + `md_im1..30`, `comment` | Every deployment has these |
| `social_autopsy` | the social-autopsy sections | |
| `intake_screen` | `introduction`, `instructions`, `confirm_inst` | Interviewer-facing preamble |
| `geography` | `survey_state`, `survey_district`, `survey_block`, `site_individual_id` | Codes come from the project's organization hierarchy |
| `narration_language` | `narr_language` | Options come from the project's language settings |
| `death_summary` | `ds_available`, `ds_count`, `ds_im1..5` | |
| `abha` | `abha_number`, `abha_address` | Web intake only |

A project's settings record which extensions it uses. The instrument a client
receives is then the WHO base plus that project's extensions — composed, not
converted, and never assembled at request time from a workbook.

### Three configuration sources, and one distinction that matters

Nothing above carries its own option lists. Three separate sources supply them,
and the two language fields are **not duplicates** — they answer different
questions:

1. **Display language** — the WHO base's own `language` ("Interview
   language"): the language the questionnaire is *shown in*. Bounded by the
   translations the system actually holds, which are standardized system-wide
   rather than per project.
2. **Narration language** — DigitVA's `narr_language`: the language the
   *narrative was recorded in*. This is data about the case; it reaches the
   coder and the SmartVA free-text path. Options come from per-project language
   check-boxes.
3. **Geography codes** (`survey_state`, `survey_district`, `survey_block`) —
   standardized in project settings, derived from the project's organization
   hierarchy, and **linked to form routing**.

An interviewer may read the form in English while the family speaks Khasi, and
the case must record Khasi: that is why both fields exist. Every deployed form
happens to offer the same short list for both, which is a property of those
deployments, not evidence that one field is redundant.

### Geography and the organization model

The `survey_state` / `survey_district` / `survey_block` fields in the ICMRVA
forms **predate the organization-unit work** and are not routing inputs.
Routing keys off `org_<level_code>_code` per decision O4 in the
[organization model plan](health-system-organization-model-plan.md), and
`MasOrgLevel.odk_field_name` derives those names.

Going forward they are standardized in project settings, derived from the
project's organization hierarchy, and **linked to form routing** — one set of
geography codes serving both attribution and routing rather than two parallel
mechanisms. The existing forms already carry recognized codes to build on:
`survey_state` = `06` (Haryana), `survey_district` = `088` (Faridabad).

### The standard field set, and configuration questions

Both standard instruments carry the same DigitVA fields, so a case looks the
same whichever form type produced it:

`unique_id`, `site_individual_id`, `Site`, `survey_state`, `survey_district`,
`narr_language`, `imagenarr`, `md_count` + `md_im1..30`, `ds_count` +
`ds_im1..5`, `Id10476` (typed narrative), `Id10476_audio`, `comment`.

`md_im*` are medical-document photos (30 slots) and `ds_im*` are death
summary/certificate photos (5); `md_count` and `ds_count` drive their
relevance. `unique_id2` is generated server-side and is not a form field.

Five of these are **configuration questions**, not interview questions:
`Site`, `survey_state`, `survey_district`, `language`, `narr_language`. Their
choice lists describe a deployment, not the questionnaire. Evidence: the three
ICMRVA forms are structurally identical — 538 questions, same names, same order
— and differ *only* in those lists.

| | `language` / `narr_language` | `Site` | `survey_state` |
|---|---|---|---|
| ND01 | english, hindi | ND01 | 06 |
| ML01 | english, khasi | ML01 | 17 |
| OD01 | english, odia | OD01 | 21 |

Each form's `Site` offers exactly one choice, because a site's form is locked
to that site. In web intake these values are injected by the server from the
draft's project-site and unit, never typed by an interviewer (see
[Web Intake Policy](../policy/web-intake.md)), so in a DigitVA client these
questions are supplied rather than asked. That is why their lists come from
DigitVA's data and not from whichever workbook was converted.

## Architecture invariants

Stated as rules that can be checked, not as aspirations. A change that breaks
one of these is wrong even if it works.

1. **One owner per concern.** Authoring belongs to the XLSForm, conversion to
   the builder, execution to the engine, persistence and authorization to
   Flask. No layer reaches past its neighbour: the engine never talks to the
   database, the Node validator never holds a session, the browser never
   decides what is valid.
2. **No second definition of a questionnaire.** Anything a form needs is in its
   workbook or derived from it. A hand-maintained parallel list is a defect.
3. **Identity is explicit.** `formTypeCode` binds mappings; the authoring
   tool's identifiers are provenance. Nothing keys off a value the form author
   can change.
4. **Refuse rather than approximate.** A type, appearance or construct the
   engine cannot honour raises by name. Silent downgrades lose interview data
   and surface far from their cause.
5. **One helper, one home.** No function exists twice. `localized` and
   `localizedRich` lived in two modules until this consolidation; that is the
   shape of mistake this rule exists to stop.
6. **Server-side truth for anything derived.** Calculated fields, validity and
   identifiers come from the server or the engine it calls, never from a
   client's assertion.
7. **Verified means exercised.** A claim of "done" cites a test that runs or a
   browser session that happened. Typecheck-only is stated as such.

## Structural debt

Named, measured, and owned — not a vague backlog. Each is a refactor with a
clear finish line.

| | Size | Problem | Fix |
|---|---|---|---|
| `vendor/who-va-2022/src/ui/question-controls.tsx` | 1554 lines | 16 controls in one factory closure; grew from 985 this session | Split per control family (text/number, choice, date/time, attachment, geo), keeping the factory as the assembly point. Unblocked: the vendored copy is ours to restructure (Q2) |
| `app/templates/va_frontpages/va_intake_form.html` | 189 lines, mostly inline JS | Draft store, API client and submit logic live in a Jinja template, so none of it can be unit tested — the two draft defects were found in a browser because there was no other way | Extract to a static ES module with the Jinja values passed in as data attributes; then test it |
| `app/services/web_intake_service.py` | 749 lines | Death register, drafts, payload building, submission and serialization in one module | Split along those seams |
| `build_instrument_from_xlsform` | ~120-line function | Reads settings, choices and survey and assembles in one pass | Extract the survey walk |

## Sequence

Ordered by dependency, not by preference.

**1. Land what exists — now, not eventually.** 36 uncommitted files across six
separable pieces, in a working tree where a second session is committing
concurrently (phases 3a and 3b landed mid-session, and one full-suite run
picked up 54 transient errors from a half-written file). Every hour these stay
uncommitted is an hour they can be clobbered or can clobber someone else. See
the commit plan below. Nothing else should start before this.

**1a. Extract the intake page's JavaScript into a testable module.** Small, and
it pays for itself immediately: the next step changes that same code to upload
attachments, and right now none of it can be tested except through a browser.

**2. Attachments and validation on the web path.** One change, because they
share `submit_draft`:
- upload endpoint through the existing attachment store;
- platform adapters that upload as the attachment is captured, never
  persisting to IndexedDB (policy path A);
- fix the `attachment_sync_pending` completion path;
- compose service + Python client for the validator, and persist the
  validator's *normalized* data so the 38 calculated fields stop being
  client-supplied.

**3. Make the engine suite trustworthy.** Stale expectations and the flaky
test. Doing this before the native app means the app is built against a green
guard.

**4. Org-unit routing for web submissions.** Largely delivered by phase 3a of
the organization model; confirm `org_<level>_code` capture on the intake page.

**5. Second questionnaire (PHMRC or Ballabgarh).** This is the real test of the
form pipeline: author the workbook, decide how DigitVA's extension fields get
in, convert, register the form type, map fields, render. Expect the converter
to need work; that is the point of doing it before the app.

**6. Native app.** Blocked on the collection policy's open C1, and on step 2
(the app needs the same upload contract). Not before the pipeline is proven by
step 5.

## Working alongside a second session

This work shares a tree and a database with another session. Two rules that
came out of it the hard way:

- **Migrations chain, and the chain is only visible once committed.** An
  uncommitted migration cannot be chained onto by anyone else; `b8e3d1f7a2c4`
  had to be re-chained onto `c1d4e7f9a3b6` after the fact. Commit a migration
  promptly or expect to re-chain it.
- **A full-suite run during someone else's edit is not a signal.** Re-run
  before believing a sudden mass failure.

## Commit plan for the uncommitted work

Six commits, each independently reviewable and each leaving the suite green:

1. **PII field registry** — `app/services/pii_field_registry.py`, migration
   `b8e3d1f7a2c4`, seed hook, tests, `field-mapping-system.md` correction.
2. **Field data collection policy** — the policy, the policy README entry, the
   cross-reference from `web-intake.md`.
3. **XLSForm converter** — builder, tests.
4. **Engine: types, appearances, inline markup** — `vendor/who-va-2022` source,
   its tests, the i18n keys, the rebuilt bundle, `.gitignore`.
5. **Engine: instrument identity** — `formTypeCode`/`source`, the element's
   `instrument` property and session handling, converter's `form_type_code`.
6. **Intake page: draft saving** — the debounce and failure-resilient queue.

The validator sidecar files (`build-validator.mjs`, `validator-server.mjs`,
`check-engine-types.mjs`, `vite.config.mjs`) go with step 2 of the sequence,
when they are wired — except `check-engine-types.mjs`, which belongs with
commit 4 because it verifies it.

## Open questions

| # | Question | Blocking |
|---|---|---|
| C1 | ~~Device credential lifetime and refresh rotation, on a shared handset~~ | **Deferred 2026-09-19:** with the native app, not open; decided when that work starts. |
| Q1 | ~~Extension fields: authored or composed?~~ | **Resolved 2026-09-18:** the deployed forms already carry them (`unique_id`, `Site`, `imagenarr`, `md_im*`), so converting a deployed form needs no composition step. Which fields exist still varies by site, so the reference form must be chosen deliberately. |
| Q3 | ~~Which deployed form is the reference?~~ | **Resolved 2026-09-18 by survey:** `NC01_DS_WHOVA2022` for WHO_2022_VA (507 questions, every standard field but the server-generated `unique_id2`); any of the ICMRVA forms for WHO_2022_VA_SOCIAL (538 questions, 10/10 standard fields, structurally identical to each other). `KEM_VAADU` and `NC01_TVA` are **not** suitable — they lack `narr_language`, `ds_im*` and, for KEM, `survey_state`/`survey_district`. Who signs off on a rebuild is still open. |
| Q4 | ~~Where do the configuration lists come from?~~ | **Resolved 2026-09-18:** narration languages from per-project language settings; geography codes from the project's organization hierarchy; display translations from the system-wide translation catalogue. |
| Q5 | ~~Are `language` and `narr_language` duplicates?~~ | **Resolved 2026-09-18:** no. `language` is the language the form is displayed in; `narr_language` is the language the narrative was recorded in. Both stay, fed from different sources. |
| Q6 | ~~How do the standardized project geography codes bind to `org_<level_code>_code` routing — same codes, or a mapping?~~ | **Resolved 2026-09-19** by [`docs/policy/va-form-project-configuration.md`](../policy/va-form-project-configuration.md): geography codes are the unit codes themselves, no mapping table; the web form fills `org_<level_code>_code` from `_unit_context`. |
| Q2 | ~~Upstream merge policy~~ | **Resolved 2026-09-18:** the vendored copy is DigitVA's own and may be restructured freely; upstream fidelity is not a constraint. |

## References

- [Web Intake Policy](../policy/web-intake.md) · [Field Data Collection Policy](../policy/field-data-collection.md) · [Organization Model Policy](../policy/organization-model.md)
- [Web intake plan](who-va-2022-web-intake-plan.md) (phase-1 detail, decisions W1–W6) · [Organization model plan](health-system-organization-model-plan.md)
- [`.tasks/who-va-2022-web-intake.md`](../../.tasks/who-va-2022-web-intake.md) · [`.tasks/who-va-engine-test-suite-stale.md`](../../.tasks/who-va-engine-test-suite-stale.md)
