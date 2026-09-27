---
title: DORIS COD Workflow
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-27
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
`app/services/cod_entry_mode.py`, shared by the coder screens
(`app/routes/va_form.py`) and the reviewer service
(`app/services/reviewer_coding_service.py`); see "Masked ICD-11 coder flow"
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
  (`_verify_doris_submission`): a changed certificate is reprocessed and
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
  the admin defaults (`_masked_reviewer_doris_context` in
  `app/routes/va_form.py`). The reviewer processes it and confirms their own
  underlying cause. `POST /api/v1/reviewing/initial/<sid>` (JSON,
  `X-CSRFToken`, 1.2 MB limit) calls `submit_reviewer_initial_cod`, which
  verifies the envelopes with `role="reviewer"` and the reviewer's active
  reviewing allocation through `_verify_reviewer_doris` (the same
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
certificate line. A WebView-based mobile shell can load the same module
with a transport that adds its own authorization header. Search results with WHO
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
click targets. Selecting a code stages its code and title in a footer; `OK`
checks it against WHO before adding the chip. A code with required
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
for both editors: the code DORIS suggests with its certificate text (or WHO
title through `codeinfo` when DORIS chose a code nobody typed), DORIS
warnings and CoDEdit report sentences as one "Check before you decide" list,
or "No problems found". A rejected or failed run says so in place of the
code. Engine status, stem, URI, readable reports and the Help rule trace sit
in a collapsed "Technical details" section at the bottom, after Step 2. Both editors are two steps.
"Step 1: DORIS" holds the certificate in DORIS's order (Part I, Part II,
fetal or infant, pregnancy context), the Process button and the result.
"Step 2: Final underlying cause of death" is always shown, says to process
Step 1 first, and shows the final UCOD field once a result exists. Each
step is its own card. Step 2 offers "Use DORIS result: <code>" when DORIS
suggested a code; clicking it runs the code through `codeinfo` and the
selection check, like a searched code. The Help field takes one verified code and is not saved;
certificate edits clear it with the results.

A new clinical certificate starts with sex and whole-year age from the
interview (`_doris_admin_defaults` in `app/routes/va_form.py`); under one
year is left to the coder. DORIS rule warnings are joined with the matching
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

## Public training service

The synthetic Help demonstration is served by `doris_public_service`, a
database-free Flask process reached through `digitva_ingress`. The ingress
sends `/help/doris-demo` and `/api/v1/doris-demo/*` to the public process and
other paths to the clinical app. The public process uses six Gunicorn request
threads, five bounded Process slots, a separate session cookie, CSRF on its
application POSTs, and a 12-second response deadline. Its read-only ECT
proxy is the sole CSRF-exempt POST. Both ingress and Gunicorn omit query
strings from access logs. Direct access to the clinical app does not serve
the public DORIS demonstration; the public hostname must point to the ingress.

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
