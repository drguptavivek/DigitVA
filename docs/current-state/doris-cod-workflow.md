---
title: DORIS COD Workflow
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-27
---

# DORIS COD Workflow

## Project setting and storage

`va_project_master.masked_cod_required` defaults to true and
`cod_entry_mode` defaults to `simple`. `icd_classification='icd11'` and
`cod_entry_mode='doris'` are equivalent (CHECK
`cod_entry_mode_classification`, migration `a3f7c1d8e5b2`, digitva-0n3): an
ICD-11 project always uses DORIS, an ICD-10 project always uses simple
entry, and the `selectable` classification is retired. Masked and DORIS
combine as the `masked_doris` mode. The mode and its predicates
(`project_mode`, `is_masked`, `is_doris`), the mode snapshot, the Part I
line 1 immediate COD and the Step 2 provenance helpers live in
`app/services/cod_entry_mode.py`, shared by the coder service
(`app/services/coder_cod_service.py`, called by the coder screens in
`app/routes/va_form.py` and by `/api/v1/coding/initial|finalize`) and the
reviewer service (`app/services/reviewer_coding_service.py`); see "Masked ICD-11 coder flow"
and "Masked ICD-11 reviewer flow" below.
Existing masked/simple and unmasked ICD-10/ICD-11 projects keep their
historical flow. The additive migration is `c7a4e2d9f1b6`.
It also adds unique indexes for active coder and reviewer finals by submission
and non-null payload version. Before applying it to an existing database,
check for duplicate active rows on those keys; the migration stops if any
exist rather than discarding or choosing a clinical record automatically.

Unmasked coding is one step: the coder's final-assessment form shows the
SmartVA result table (`app/templates/va_form_partials/_smartva_summary.html`,
shared with the masked final step) above the simple fields or the DORIS
certificate. An unmasked/simple coder or reviewer submits one final assessment with an
immediate COD, an underlying COD and optional associated-condition text. In
unmasked/DORIS, the MO enters a Part I/II certificate, processes it, reviews
the DORIS and CoDEdit outputs, and independently confirms a final underlying
COD. The reviewer has a separate editor and final row; the coder certificate
can be copied into it without changing the coder's record.

Both final-assessment tables store the final certificate, independent DORIS
and CoDEdit envelopes, human final COD, and a snapshot of project mode, ICD
release and WHO image digest. The final COD remains the value used by final
authority and COD bucket reporting. No intermediate Process call writes a
draft or assessment row.

## Masked ICD-11 coder flow

A masked ICD-11 (`masked_doris`) coder keeps Step 1 and Step 2
(digitva-0n3 phases 2 and 3).

- **Step 1** is the unmasked DORIS editor
  (`_doris_certificate_editor.html`) without SmartVA anywhere in the page:
  certificate, Process, and the coder's final-cause card ("Use DORIS result"
  or the coder's own code through the picker's search). The save reuses the
  unmasked final save's verify-or-reprocess path
  (`verify_doris_submission` in `reviewer_coding_service.py`, role `coder`):
  a changed certificate is reprocessed and
  returned as a 409 with a fresh proof. The Step 1 row
  (`va_initial_assessments`) stores the verified certificate, DORIS and
  CoDEdit envelopes and the mode snapshot. Its text columns are derived:
  `va_immediate_cod` is the first condition on Part I line 1 (`<code>
  <text>`, or the text alone when uncoded) and `va_antecedent_cod` is the
  coder's confirmed underlying cause, checked against the local catalogue as
  the unmasked final UCOD is. An empty Part I line 1 or no confirmed cause
  is a 400. The DORIS clinical API (`_clinical_context`) accepts a masked
  DORIS project for the coder and the reviewer, each only with their own
  active allocation for that role; a masked ICD-10 project stays 409
  `DORIS_NOT_ENABLED`.
- **Reopening a saved Step 1** (active Step 1 row with a DORIS result) shows
  the saved result and underlying cause through the editor's
  `doris_initial_processing` input, with no process token (none is minted on
  GET). "Continue to Step 2" loads Step 2 without re-saving. Save stays
  disabled: editing the certificate, or choosing a different underlying
  cause, needs Process and Save again (the cause can also be changed in
  Step 2). Unmasked DORIS reopen is unchanged.
- **NQA gate.** When the project requires the Narrative Quality Assessment
  and this coder has none for the current payload, a successful Step 1 save
  (masked simple and masked DORIS) responds with `_nqa_required_notice.html`
  instead of the Step 2 form, as the Step 2 GET does. Step 1 is still saved.
- **Step 2** shows the SmartVA table, a read-only summary of the Step 1 DORIS
  run (`doris_result_summary.js` over the Step 1 envelopes) with the Step 1
  underlying cause, and three choices: "Use Step 1 underlying cause" (the
  cause the coder confirmed in Step 1, not DORIS's computed code, which the
  summary shows for information), "Use SmartVA result", or the coder's own code through
  the picker's search (`app/static/js/doris_final_cod.js`, a small host of
  `digitva_icd11_picker.js`). There is no second certificate and no Process;
  a Step 2 save that posts a certificate or process proof is a 400. The
  SmartVA choice is WHO's ICD-10-to-11 target for SmartVA's primary cause
  (`smartva_icd11_mapping`): one click when the map gives a single
  expression, otherwise a search prefilled with the first `/` alternative.
  No WHO call decides this; the chosen code is checked at save as the
  unmasked final UCOD is. A recode presets the picker with the previous
  active final code, as the masked simple flow does. Inside masked Step 1
  the embedded editor's headings read "DORIS certificate" and "Underlying
  cause of death" (template variables `doris_step1_title`,
  `doris_step2_title`); unmasked DORIS keeps "Step 1: DORIS" / "Step 2".
- The final row stores no envelopes (they stay on the Step 1 row, linked by
  `source_initial_assessment_id`). Its `cod_entry_mode_snapshot` adds
  `final_ucod_source`: `doris` when the final code expression equals the
  Step 1 underlying cause, else `smartva` when it equals any alternative of
  the SmartVA target, else `own`. It is derived server-side; a code equal to
  both is `doris`. Other modes' snapshots are unchanged.

## Masked ICD-11 reviewer flow

A masked ICD-11 reviewer (digitva-0n3 phase 4) follows the coder's two
steps on the reviewer COD panel
(`app/templates/va_formcategory_partials/_va_cod_assessment_panel.html`),
where Step 1 and, once saved, Step 2 sit on one page.

- **Step 1** is the DORIS editor with `doris_role='reviewer'` and no SmartVA.
  It is seeded (deep copy) from the reviewer's own active Step 1 row when it
  has a certificate, else from the certificate of the coder's Step 1 behind
  the authoritative coder final (`source_initial_assessment_id`), else from
  the interview prefill (`masked_reviewer_context` and `doris_initial` in
  `app/services/doris_context_service.py`). The reviewer processes it and confirms their own
  underlying cause. `POST /api/v1/reviewing/initial/<sid>` (JSON,
  `X-CSRFToken`, 1.2 MB limit) calls `submit_reviewer_initial_cod`, which
  verifies the envelopes with `role="reviewer"` and the reviewer's active
  reviewing allocation through `verify_doris_submission` (the same
  verify-or-reprocess helper as the unmasked DORIS reviewer final), and
  stores them with the mode snapshot on `va_reviewer_initial_assessments`.
  The text columns are derived as for the coder; only the underlying cause
  gets catalogue provenance. The coder's rows are never written.
- **Reopening** shows the saved result and cause without a process token
  and offers "Continue to Step 2", an anchor to the Step 2 form below.
- **Step 2** shows SmartVA, the reviewer's Step 1 DORIS summary and the
  same three choices as the coder (`_masked_doris_final_cod.html` with
  `masked_final_form_id='reviewerFinalCodForm'`), posted to
  `/api/v1/reviewing/finalize/<sid>`. Posting any envelope field is a 400.
  The reviewer final row stores no envelopes (SQL NULL) and records
  `final_ucod_source` against the reviewer's own Step 1 cause.
- **Masked ICD-10 reviewer** Step 2 now also shows the SmartVA table
  (display only); Step 1 and the save are unchanged.
- The reviewer saves are not refused for a missing NQA (the NQA only
  blocks moving on from the narration section), so the coder's Step 1 NQA
  notice has no reviewer counterpart.

## Step 2 picker and quick-use choices (digitva-u6e1)

The masked Step 2 final search (`_masked_doris_final_cod.html`,
`doris_final_cod.js`) uses the shared ICD-11 picker in final mode, the same
search the DORIS editor's final box uses: WHO terms, or codeinfo for a code,
then `picker.renderResults(..., finalMode: true)`. It keeps the hidden
`conclusive_cod` field and the save path. Auto-search starts at 3 characters.

The quick-use buttons show code and ICD-11 title, and for SmartVA also the
cause and likelihood (for example "Use SmartVA result: 1B10.1 — Tuberculosis
(TB, somewhat likely)"). Titles come from the local WHO ICD-11 API
(`icd_api_service` via `get_icd11_codeinfo`, the call DORIS uses), never from
`mas_icd11_mms`. codeinfo carries no title of its own, so the title is the one on
the stem entity its `stemId` points at, read as `_codeinfo_item` reads it. `app/services/icd11_titles.py` looks each code up once per
page build and caches the result for `ICD_SEARCH_CACHE_TIMEOUT`. A postcoordinated
expression gets its stem and extension titles joined with ` + `. If the API is
unavailable the page shows the code alone (the stored Step 1 text when it has a
title), and the lookups for that request stop after the first failure. The same
labels reach the Expo app in the workspace payload (`antecedent_cod_label`,
SmartVA cause `icd11_label`), so the app makes no title call for them. The
SmartVA "ICD-11 mapping" badges on the web and in the Expo SmartVA card carry
the same titles.

## Check before you decide

Known DORIS warnings are explained in plain language with the code and its
ICD-11 title filled in; the DORIS text stays smaller underneath. The catalogue
and what it says are in `docs/policy/doris-certificate-rules.md` (section
"Warning catalogue"). Web: `doris_warnings.js` reads
`doris_messages.js`, and titles come from the codeinfo endpoint after the first
paint. Expo: `dorisWarnings.ts` reads `dorisMessages.ts`, and the titles come
from `getDorisCodeInfo`. Both tables are generated by
`scripts/generate_doris_messages.py`; `tests/fixtures/doris_warning_cases.json`
is run by `tests/js/doris_warnings_check.mjs` and by the Expo parity test.

## Process and final save

New blank Help and clinical certificates show three Part I lines. Loaded
certificates retain their stored line count. Each line has a numeric interval
and unit selector after its code entry; single-unit values are serialized as
ISO 8601 durations on every condition in the line. Loaded composite or unknown
durations remain unchanged until the coder edits the interval. Empty trailing
lines are omitted from processing, and a blank line between filled lines is
blocked. Search results display code, title, context and actions in compact
rows. An interval edit clears the clinical processor results and final UCOD.
The server validates nonempty interval durations before WHO processing and
final save; empty and WHO unknown markers remain accepted.

The editor and picker look (native components, shadcn tokens, light and dark)
is described in [DORIS Editor UI Tokens](doris-ui-tokens.md).

The public Help certificate and the clinical coder/reviewer certificate
share one framework-free ES module, `app/static/js/digitva_icd11_picker.js`
(`createIcd11Picker({mount, transport, onSelect, onClose, revision})`). The
host supplies the mount element and a `transport.post(name, body)` that
maps logical route names (`terms`, `codeinfo`, `selection-check`,
`postcoordination`, `postcoordination-options`, `hierarchy`, `related`,
`details`) to its own URLs with CSRF and credentials; the picker reads no
globals, cookies or dataset values. `doris_demo.js` and `doris_clinical.js`
are ES module hosts loaded with `type="module"`; the clinical host owns the
HTMX close hook. `doris_interval.js` is a separate module owned by the
certificate line. The Expo app (browser and native) reuses the same picker
through `app/static/doris_picker_host.html` and `digitva_icd11_embed.js`,
shown in an iframe (browser build) or a WebView (native, from the enrolled
server). That page holds no credentials: each WHO call is a `{path, body}`
message answered by `mobile/digitva-collect/src/workspace/doris/pickerBridge.ts`
through the authenticated client, and only a code the server verified with
selection-check reaches the certificate. The shared `renderResults` draws the
result rows for both hosts. A `doris_demo.css` media query at 768px makes the
modal a single full-screen column, the host page takes `?theme=dark|light` (default
the system setting; `data-bs-theme` on `<html>` drives the `doris_demo.css` dark
block) and `?q=<term>` (or a `{t:'search', query}` message) to search a typed
term as soon as the modal opens, and a host can tint the modal header per
certificate line with `doris-line-accented` and `--doris-line-accent`.
Search results with WHO
postcoordination availability offer a stem builder, while complete expressions
remain directly selectable. The builder obtains the pinned WHO release's axes
through DigitVA's CSRF-protected public or clinical POST API, labels required
axes, and lazily loads bounded child choices. The hierarchy view shows the
ancestor path and nearby nodes. Uncoded WHO folders can be expanded but are
not selectable. The browser previews `&` extensions and `/` additional stem
codes as one condition, then calls the existing server selection check before
adding one chip. The clinical editor's existing edit path invalidates current
processor results, process proof, and final UCOD after a chip changes. The
vendored WHO ECT remains available from the editor.

The condition search now opens in a large modal. The code row, `+ Build`,
maternal `J`, perinatal `K`, coding-note marker and Details action have distinct
click targets. Selecting a code stages its code and title in a prominent footer
(`SELECTED`, or `BUILDING` during a guided build; see `doris-ui-tokens.md`); `OK`
checks it against WHO before adding the chip. On a phone, `+ Build`, Details and
related-term links scroll their card to the top of the results pane and offer
"Back to results". A code with required
postcoordination opens its details and choices immediately. Required choices
appear first on screen, each axis is headed with WHO's instruction wording
and offers a search limited to that axis's WHO subtree, and a final "Other
postcoordination?" search over the extension chapter appears for MMS
category stems outside that chapter; an open-ended pick is accepted only
if WHO codeinfo resolves it with the stem. Uncoded folders render as
expandable `▷` nodes with no select control. The expression puts `&`
extensions before `/` stems, each group in WHO axis order, matching WHO's
canonical form. Maternal and perinatal panels list WHO's exact composite
category first. Details include available matching terms,
definition, fully specified name, inclusions, exclusions and coding notes.
Reset clears the modal query, results and staged choice without removing
certificate codes already added to the line.

The shared normalization and traversal service is
`app/services/icd11_postcoordination.py`. Public routes are under
`/api/v1/doris-demo/`; clinical routes with case authorization are under
`/api/v1/doris-clinical/`. Both expose `postcoordination`,
`postcoordination-options`, and `hierarchy`, and both `terms` routes share
one `search_terms` service function that accepts optional `subtree_uris`
and forwards them as WHO's `subtreesFilter`. WHO's exact multiple-value rule
is preserved, including the restriction against two choices from the same
block. A two-slot guidance limit and bounded call budget protect request
capacity. When a root or child option list has more than 12 choices, the response
marks it truncated; coders can expand visible WHO folders and select a complete
expression once required axes are satisfied, or search for a complete
expression. No schema change or new
stored data is involved.

The authenticated `/api/v1/doris-clinical/process/<va_sid>` endpoint checks
form access, role, active allocation, active submission payload and project
mode. It validates the certificate and its selected ICD-11 code/URI pairs
against the pinned local WHO release, then calls DORIS and CoDEdit
independently. The response has separate processor statuses and a short-lived
signed token binding certificate and result digests to the case, actor,
allocation, payload version, release and WHO image.

Results open as a short summary built by `app/static/js/doris_result_summary.js`
for both editors, laid out as on the Expo screen: "DORIS: completed", then
"Underlying cause: CODE title" with each manifestation as "+ CODE title
(manifestation)" (or the bare code and its certificate or WHO title when the
server sent no computed parts), the full code as a monospace chip only when it
differs from the first code, and a collapsed "Details" with the "/" and "&"
explanation, stem and URI. DORIS warnings and CoDEdit report sentences form one
"Check before you decide" list, or "No problems found". A rejected run says
"DORIS rejected the certificate." and shows WHO's reason; a run that did not run
(unavailable) says so in place of the code. Engine status, readable reports, the
CoDEdit issue IDs and the Help rule trace sit in a collapsed "Technical details"
section at the bottom, after Step 2. Both editors are two steps.
"Step 1: DORIS" holds the certificate in the WHO DORIS screen's wording and
order, in the web editor and the Expo app alike: "Administrative Data" (sex,
estimated age and age unit, date of birth, date of death), "Frame A: Medical
data" with "Part 1: Cause of death" (lines lettered A to E; our "Immediate
cause" / "Due to" titles stay, each line has "Interval" and "Time unit"),
"Part 2: Other significant conditions contributing to death" (one heading,
one "Significant conditions contributing to death" tile), then the separate
cards "Manner of death", "Fetal or infant death *", "Information on
pregnancy", "Surgery" and "Autopsy", a "*fields are not mandatory" footnote,
the Process button and the result. The blank choice reads "Not stated".
Which controls show is set by the field rules in
`docs/policy/doris-certificate-rules.md` (V1 to V12): the fetal card only under
one year (hours survived only under 7 days and not stillborn), "Information on
pregnancy" only for sex female (its two follow-up questions stay disabled until
the first answer is Yes; while it is not Yes they are blanked and not sent, and
`drop_inapplicable_sections` drops them server-side too), surgery date and reason only after Yes, autopsy
findings only after "requested", and the external-cause fields only for manner
codes 1 to 7. `app/static/js/doris_rules.js` is the pure module (no DOM) that
`doris_clinical.js` calls on every edit. A whole card that does not apply (fetal, pregnancy)
keeps its title and shows a yellow `alert-warning` note ("This section is not
applicable when ...", `NOT_APPLICABLE` in `doris_rules.js`, identical wording in
the Expo editor); single follow-up fields just hide. Hidden controls get `hidden`, are
emptied, and are dropped from the certificate sent to `/process` and saved, so
they start blank if shown again. Soft warnings (pregnancy age band 10 to 54,
interval longer than the age or shorter than the line above, date order,
estimated age against the dates, plausibility ranges) appear under the field in
the form-text style and never block Process or Save; interval units longer than
the age at death are greyed. The reported age is the editor's estimated age,
and the data attribute `data-today` carries the user's local day.
`normalize_certificate` also drops the hidden keys
(`drop_inapplicable_sections`), so a stale client cannot send a fetal section for
an adult, and the prefill applies the same function. Node check:
`node tests/js/doris_rules_check.mjs`. Each Part I/II line reads "Onset to
death [Interval] [Units]" (the age control keeps "Age" / "Age unit"), each Part I
line has its own "Add line" that inserts below it (cap 5, letters renumber), and
the editor and picker tint outline buttons for dark mode in `doris_demo.css`. Dates
(birth, death, injury, surgery) hold the ISO day, with no `max` (native
validation would block Save in the htmx form; problems are soft warnings,
V10). Date of birth, Date of injury and Date of surgery have a precision
select (Date / Year-Month / Year) beside the input, which switches between a
date, a month and a 4-digit year input and stores `YYYY-MM-DD`, `YYYY-MM` or
`YYYY` (`doris_fields.js`; a saved value opens in its own precision). Date of
death is a plain calendar input; a saved partial value shows in a text input
until replaced. Every question in Administrative Data, Manner of death, Fetal
or infant death, Information on pregnancy, Surgery and Autopsy has a clear
button (`data-doris-clear`, shown only with a value; clearing fires input and
change, so rules, warnings and the "from interview" badge update). The line and
final-cause search boxes start searching after 3 characters and a 500 ms pause
(`attachAutoSearch` in `digitva_icd11_picker.js`); Search and Enter stay
immediate. Node check: `NODE_PATH=mobile/digitva-collect/node_modules node
tests/js/doris_fields_check.mjs`. The web user's day comes from
`current_user_today` (user profile zone; Expo: the device zone). Option codes in the
Expo app are DORIS's own (Manner of death 0 = Disease), the same as the web.
Fields the interview prefilled carry "from interview (IdNNNNN)" in both.
Estimated age is always prefilled when the interview answered the age, even
with both dates known. The Part I move up, move down and remove buttons have a
solid 1.5px border (remove in red) in light and dark.
"Step 2: Final underlying cause of death" is always shown, says to process
Step 1 first, and shows the final UCOD field once a result exists. Each
step is its own card. Step 2 offers "Use DORIS result: <code>" when DORIS
suggested a code; clicking it runs the code through `codeinfo` and the
selection check, like a searched code. The Help field takes one verified code and is not saved;
certificate edits clear it with the results.

A new clinical certificate starts with the non-cause fields the interview
answers (`digitva-hln`): `doris_initial` in
`app/services/doris_context_service.py` (called by the web partials and, as
`workspace_doris`, by `GET /api/v1/va/<sid>/workspace`) reads
the active payload version and calls `doris_prefill_from_payload` in
`app/services/doris_prefill.py`, one pure function for web and ODK cases
that follows the mapping in `docs/policy/doris-cod-workflow.md`. Masked
Step 1 gets it too (interview facts, not SmartVA). A saved certificate is
shown as saved, without prefill. Each prefilled control carries a "from
interview (Id…)" badge from the `data-doris-prefill` map; every value stays
editable. At every certificate save (coder masked Step 1 and unmasked
final, reviewer masked Step 1 and unmasked final) the server recomputes the
prefill from the same payload and stores
`cod_entry_mode_snapshot["doris_prefill"]` = `{"version": 1, "fields":
{"Section.Field": {"sources": [...], "changed": bool}}}`: which fields the
interview prefilled and whether the saved certificate differs, with no
answer values. Every web project's form carries the
`doris_support_whova_2022` extension (always on, like `digitva_core`),
whose questions fill the gaps; ODK cases use the WHO-question fallbacks
until their workbooks take the rows generated from that extension. DORIS rule warnings are joined with the matching
line of DORIS's report, and CoDEdit back-end keys are shown as WHO's
published sentence. After an edit the status reads "Certificate changed.
Process it again before saving." If a save is refused for another reason,
the re-rendered form carries the processed result, token and chosen final
UCOD back (`data-doris-initial-processing`), so the coder need not process
again; the token is re-checked at the next save. The coding page's side
browser tab opens ICD-11 for ICD-11 projects and ICD-10 otherwise.

Every certificate edit clears the browser's processor results and human UCOD
choice. At final save, the server normalizes the submitted certificate and
checks both processor envelopes and the signed token. A changed certificate
is reprocessed and returned as `409 DORIS_CERTIFICATE_CHANGED` with fresh
results; no row is saved until the MO reviews and confirms a UCOD again. An
expired or mismatched token also requires fresh processing. An exact match
saves the final certificate, processor outputs and independently validated
human UCOD in the same transaction as the existing workflow and audit changes.
WHO processor failure is advisory when codeinfo verification still works;
codeinfo failure blocks final ICD-11 provenance validation.

## ICD-11 provenance: primary stem, age confirmation, causing condition

Every saved ICD-11 COD pick carries server-built provenance in its row's
`icd11_provenance`, keyed by field: `conclusive` for a final, `immediate`
for a final's immediate cause, `antecedent` for a Step 1 underlying cause
(`app/services/icd11_mms_service.py`, `build_icd11_provenance`). Keys:

- `code`, `title`, `selected_text`, `release`, `linearization_uri`,
  `foundation_uri`, `codeinfo_uri`: the expression and its WHO URIs.
- `primary_stem` (`digitva-443q`): the stem allowability and the VA cause
  use. WHO's causing condition (`hasCausingCondition[0]` in codeinfo) when
  WHO reports one, so `FB80.B/2F9Z` is `2F9Z`; otherwise the first stem
  (docs/policy/icd11-code-selection-principles.md, principle 13).
- `age_restriction_confirmation` (`digitva-oh7j`): `{confirmed_by,
  confirmed_at, code, age_group_selectable, restriction_note,
  doris_warning}`, present only when the coder or reviewer confirmed an age
  conflict. `doris_warning` is DORIS's plausibility warning when it names
  this code, else null.
- `causing_condition_unknown: true` (`digitva-xmpx`, finals only): WHO's
  causing condition was not known, so the stem stands alone.

**Sex blocks, age warns** (docs/policy/who-2022-icd11-coding-allowability.md,
"Sex and age"). The validator refuses a sex conflict as before and raises
`AgeRestrictionConfirmationRequired` (`app/services/icd_coding_policy.py`)
for an age-only conflict. The coder's and reviewer's final underlying COD
and, in masked DORIS, their Step 1 underlying cause (`antecedent_cod`,
owner 2026-10-27) are then refused `422` with
`{"error", "code": "AGE_RESTRICTION_CONFIRMATION_REQUIRED",
"age_restriction": {"code", "age_group_selectable", "restriction_note"}}`
unless the request sends `age_restriction_confirmed: true` (a JSON boolean;
anything else is `400 invalid_request`; the web form posts `true`). The
confirmed save records `age_restriction_confirmation` on that field. Paths:
`POST /api/v1/coding/initial|finalize/<sid>` (`app/routes/api/coding.py`),
`POST /api/v1/reviewing/initial|finalize/<sid>`
(`app/routes/api/reviewing.py`), the web Step 1 and Step 2 forms
(`app/routes/va_form.py`); services `submit_coder_initial_cod` /
`submit_coder_final_cod` (`app/services/coder_cod_service.py`) and
`submit_reviewer_initial_cod` / `submit_reviewer_final_cod`
(`app/services/reviewer_coding_service.py`). Certificate lines (Part I
line 1, the masked simple and final immediate causes) are not confirmable:
an age conflict there is refused as before. Masked simple is ICD-10 only
(ICD-11 means DORIS), so its Step 1 never meets the confirmation. A station
bundle cannot confirm: its final keeps the rejection `final_blocked`
(`_apply_coding`, `app/services/bundle_ingest_service.py`). The selection
check returns the age conflict as a `warnings` entry
`{code: "AGE_RESTRICTED", ...}`, and search marks age-restricted codes
(`age_restricted`, `restriction_note`) instead of hiding them.

`causing_condition_unknown: true` on a final is accepted only for one
ICD-11 stem without `/` (`&` extensions allowed); otherwise `422
INVALID_CAUSING_CONDITION_FLAG`.

**Readers use the primary stem.** The COD snapshot and detail MVs bucket
an ICD-11 final by `icd11_provenance -> 'conclusive' ->> 'primary_stem'`,
else its first stem (`icd11_primary_stem_sql`,
`app/services/submission_analytics_mv.py`; migration `c5e8a2f4b7d1`
rebuilt both views). The snapshot exposes `coder_final_icd11_stem`,
`reviewer_final_icd11_stem` and `authoritative_icd11_stem`, and the COD
snapshot export's `*_icd11_stem_uri` columns are those stems' URIs. In
Python, `icd11_primary_stem_of(value, provenance_item)`
(`app/services/icd_coding_value.py`) does the same for the training report
(`app/services/training_cause_groups.py`,
`app/services/training_report_service.py`). The VA definition lookup
(`find_va_definition_for_icd`, `app/services/va_cause_definition_service.py`)
uses a saved value's `primary_stem`; for a bare `/` cluster it asks WHO
codeinfo once (cached), and any other value never calls WHO.

## Public training service

The synthetic Help demonstration is served by `doris_public_service`, a
database-free Flask process reached through `digitva_ingress`. The ingress
sends `/help/doris-demo` and `/api/v1/doris-demo/*` to the public process and
other paths to the clinical app. The demo follows the coding screen: `codeinfo`
and `selection-check` accept only the code asked for and its own expression URI
(no stem fallback), `selection-check` takes exactly `schema_version`, `code`
and `uri`, a line takes at most 8 conditions (the server cap), the condition
text is the WHO title, and a processing run with no engine completed (HTTP 503
with the full envelope) is shown as the normal summary. Its soft warnings are
the `doris_rules.js` ones whose inputs the demo has (no date or injury fields,
so the date-based warnings do not fire there). The public process uses six Gunicorn request
threads, five bounded Process slots, a separate session cookie, CSRF on its
application POSTs, and a 12-second response deadline. Its read-only ECT
proxy is the sole CSRF-exempt POST. Both ingress and Gunicorn omit query
strings from access logs. Direct access to the clinical app does not serve
the public DORIS demonstration; the public hostname must point to the ingress.

The anonymous `/help/icd11-codes` browser links to this synthetic, unsaved
demo through the ingress. In local debug, the clinical app shows that link
only for `localhost:8051` or `127.0.0.1:8051` and targets the local ingress on
port 8052. A remote host served directly by the clinical app does not show
that development link.

The ingress passes incoming `X-Forwarded-For` and `X-Forwarded-Proto` through
unchanged, falling back to its own peer address and scheme only when they are
absent, so both apps' `ProxyFix(x_for=1, x_proto=1)` see the client address
and `https` set by the upstream TLS reverse proxy. The trust boundary is the
cloud firewall: only the reverse-proxy VM may reach the ingress. If the ingress
port were reachable by clients directly they could spoof their address; the
upgrade path is nginx `real_ip` with `set_real_ip_from` the reverse proxy.
The ingress re-resolves `minerva_app_service` and `doris_public_service`
through Docker DNS every 10 seconds, so restarting or recreating either app
does not leave the ingress returning 502 until it is itself restarted.

Production wiring: the DMZ reverse proxy terminates TLS for the public hostname
and sets `Host`, `X-Real-IP`, `X-Forwarded-For` and `X-Forwarded-Proto`; it is
not changed for the ingress. Routing is local to the app VM: its untracked
compose override publishes the ingress on the port the proxy already targets
and no longer publishes `minerva_app_service` (the base compose file binds the
ingress to loopback only). The app VM runs with `COMPOSE_PROFILES=icd11` and
`DORIS_PUBLIC_COOKIE_SECURE=true`.

The pinned WHO image is `whoicd/icd-api:2.6.0` with MMS `2026-01` and image
digest `sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c`.
Changing that digest requires a fresh contract and fixture review.
The clinical process refuses a `DORIS_WHO_IMAGE_DIGEST` environment override
that differs from this pinned digest. Before routing a production hostname to
the ingress, configure a secure public cookie for TLS and verify the deployed
WHO image digest and ingress log format against this release.

Policy: [DORIS COD Workflow Policy](../policy/doris-cod-workflow.md).

## WHO date-pair crash (2026-10-24)

Reproduced on the pinned `whoicd/icd-api:2.6.0` image: DORIS answers "Internal
system error" (`reject: true`) and CoDEdit answers HTTP 500 when
`AdministrativeData.DateBirth` and `DateDeath` are both present and either is
year-only (`YYYY`). Month precision (`YYYY-MM`), a full date, either date alone,
an absent date, an age inconsistent with the dates, manner of death and the
external-cause fields are not triggers. `who_safe_certificate`
(`app/services/doris_certificate.py`) leaves the year-only date out of the
request to both WHO engines only; the stored certificate, its digest and the
coder's entry are unchanged, and `process_certificate` returns `who_notes`
naming what was left out. The Expo result panel suppresses this technical
date-omission note; it remains in the processor response for diagnostics.
A remaining WHO "Internal system error" also adds a `who_notes` line telling the
coder to check the certificate or choose the cause without DORIS.

## Inline VA reference and SmartVA refresh

The Expo editor shows the mapped VA cause code and title below suggested and
selected ICD causes in either coding step. The selected cause's plain-text case
definition is an expanded note beside the selection on desktop, stacked below
on phones. Its DigitVA attribution is retained; WHO metadata stays in the details
sheet. Lookups are shared by API instance and ICD code, with rejected requests
evicted so a later attempt can recover.

`GET /api/v1/coding/submissions/<sid>/smartva` is an authorized, read-only status
response containing only `va_sid`, `status`, and `can_run`. It uses the same
coding/review/triage scope checks as the existing CSRF-protected POST action.
The case-screen lifecycle starts a missing run when coding begins and polls
queued/running work in the foreground independently of the navigation drawer.
Terminal status reloads the permitted result once; masked Step 1 still receives
no SmartVA result. Atomic enqueue claims avoid duplicate dispatch from concurrent
case opens. The intake after-commit path uses its known fresh-payload context
without adding outcome queries to the submission path.

## Readable computed UCOD (2026-10-24)

DORIS returns the computed UCOD as raw codes (`5A14/BA41.Z`, `A&X/B`, URIs
joined by `/` with a trailing `/unspecified`). `process_certificate` also
returns `ucod_parts` (`app/services/doris_processing.py` `ucod_parts`): one
`{code, title, role, uri}` per code, `role` being `stem`, `extension` (after
`&`) or `postcoordinated` (after `/`). Titles come from the certificate's own
text for that code, else `icd11_title` (WHO ICD API, cached, English); a failed
lookup leaves `title` empty and never fails the result. The Expo result panel
(`DorisPanel.tsx` `ProcessingSummary`) and the web summary
(`doris_result_summary.js`) show "Underlying cause: CODE title" then "with CODE
title (postcoordinated manifestation)", a one-line explanation of `/` and `&`,
and keep the raw code and URI muted underneath. The parts are not part of the
result digest or the process proof. A save stores them inside the saved DORIS
result (`doris_result` JSON, no schema change): `verify_process_submission`
recomputes `ucod_parts` and `who_notes` from the verified certificate and DORIS
envelope (never from the client), and `bundle_ingest_service` stores the same
keys. The reopened Step 1 and Step 2 context (`doris_context_service.py`
`saved_step1_processing`, `masked_step2_context`) returns them top-level beside
`doris`, `codedit`, so the reopened result shows the same titles and notes.
Rows saved before this has `[]` for both and show the raw codes as before. The
Step 1 suggestion's title is looked up by its stem (`stemCode`), not by the full
computed UCOD, which WHO does not know.
## DORIS call debug log (owner decision 2026-10-24)

Policy note: to debug DORIS failures the owner approved logging the full data
sent to and received from WHO DORIS and CoDEdit. This is a temporary, opt-in
debug aid, off by default, and must be switched off once the fault is found.

- Enable: set `DORIS_CALL_LOG=1` in the staging `.env`, then restart
  `minerva_app_service` (and the Celery services if they run the check). Unset
  or `0` disables it.
- Output: one JSON line per engine call (two per certificate check) in
  `logs/doris_calls.log`: `ts`, `engine` (`doris`|`codedit`), `case` (first 10
  hex of the SHA-256 of the `va_sid`), `actor_role`, `ms`, `http_status`,
  `request` (the exact body sent to WHO, after `who_safe_certificate`),
  `response` (the exact JSON WHO returned, or the text or status for a
  non-JSON or failed reply), `omitted` (fields left out of the WHO request) and
  `app_outcome` (`accepted`|`rejected`|`http_error`).
- Privacy: no names are in a certificate. Free text (condition `Text`,
  `Reason`, `DescriptionExternalCause`, `PerinatalDescription`) is replaced by
  `[text N chars]`; codes, URIs, dates, sex, age, durations and manner are kept.
  The `va_sid`, user email and tokens are never written. WHO's own `report`
  text in the response is logged as returned.
- Read: inside the container `/app/logs/doris_calls.log`; on the host the bind
  mount `<repo>/logs/doris_calls.log`. e.g. `jq -c 'select(.app_outcome!="accepted")' logs/doris_calls.log`.
- Retention: rotated daily, gzipped (`doris_calls.log.<UTC date>.gz`), 7 files
  kept, so about a week. Delete the files when the debugging ends.
- Always on, flag or not: one INFO line in the normal app log,
  `doris_call engine=… case=… outcome=… status=… ms=… error="…"`; read with
  `docker logs minerva_app_service 2>&1 | grep doris_call`.
- Logging never raises: a failed write is warned once and the check proceeds.
