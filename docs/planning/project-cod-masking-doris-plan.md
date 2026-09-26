---
title: Project COD Masking and DORIS Entry Plan
doc_type: planning
status: proposed
owner: engineering
last_updated: 2026-09-26
---

# Project COD Masking and DORIS Entry Plan

## Status and decision

Planning only. Do not implement yet. The owner agreed to two project settings
and the flows below on 2026-09-26, then requested an interactive proof on a
public Help page **before** any production COD workflow change. Implementation
is tracked by `digitva-ddv.1` and awaits review of this plan.

This plan supersedes the optional-Step-1 proposal in
`docs/planning/icd11-coding-screen-integration-plan.md` for the COD workflow.
That older document also contains completed ICD-11 catalog work; those parts
are not superseded.

## Product contract

| Masked COD required | COD entry | Coder | Reviewer |
| --- | --- | --- | --- |
| Yes | Simple | Current blind Step 1, then SmartVA and final COD Step 2 | Current blind reviewer Step 1, then coder COD and SmartVA with final reviewer Step 2 |
| No | Simple | SmartVA visible on entry; one human form with immediate COD, underlying COD, associated conditions | Coder COD and SmartVA visible on entry; one human final review with the same three fields |
| No | DORIS | SmartVA visible; MO completes DORIS cause chain, sees computed underlying COD, rationale and advisory CoDEdit findings, then chooses final underlying COD | Coder COD and SmartVA visible; reviewer examines/edits the chain, sees DORIS and advisory CoDEdit output, then chooses final underlying COD |

Masked + DORIS is invalid. DORIS is an ICD-11-only project choice. The
existing masked + simple configuration remains the default for every current
project. SmartVA and DORIS guide the MO; neither automatically becomes the
authoritative COD. Coder and reviewer decisions remain separate.

For simple unmasked entry, the final assessment must hold all three fields.
The immediate and underlying codes use the existing ICD picker and server
validation (WHO ECT for ICD-11); associated conditions are optional. The
underlying field alone drives final-COD authority and VA bucket reporting.
There is no artificial Step 1 row in an unmasked project.

For DORIS entry, the MO records Part I as ordered lines, each with one or
more conditions, plus Part II conditions and known intervals or contextual
fields. Each coded condition retains text, the full ICD-11 code or cluster,
and verified WHO URI provenance. A cluster is one coded condition, not a
causal edge. The DORIS form is the input, followed by a separate final
underlying COD field chosen by the MO. Show the DORIS-computed underlying
COD, rule rationale, warnings, or rejection as soon as the form can be
processed. The MO may choose the same or a different final code. Store the
DORIS input and result separately from the human final code, without an
override label or required override reason. CoDEdit's completeness and
consistency findings are advisory only and saved separately; they do not
block the final human choice.

Missing information is inherent to verbal autopsy. Do not require the MO to
invent unknown intervals, dates, clinical facts, or causal links. Send only
available fields, using WHO's unknown values when appropriate. If DORIS
cannot process an incomplete certificate or the local API is unavailable,
show the failure and still allow the MO to choose the final underlying COD.
Never represent a failed DORIS attempt as a computed COD. Automatic
prefilling and suggestions from VA answers are a later design task; this
release must not infer certificate content silently.

## Current implementation and reuse

- `va_project_master` already holds project workflow and ICD classification
  settings; add the new settings there, not in per-form ODK mapping.
- `app/templates/va_formcategory_partials/_va_cod_assessment_panel.html`
  currently selects the coder initial or final partial by existence of an
  initial row, and renders both reviewer steps together. Branch by the
  project setting instead.
- `app/services/workflow/transitions.py` already accepts coder finalization
  from `coding_in_progress`; no new workflow state is needed.
- `app/services/reviewer_coding_service.py` currently requires a reviewer
  initial assessment before reviewer finalization. Keep that rule for masked
  projects and waive it only for unmasked projects.
- `va_final_assessments` and `va_reviewer_final_assessments` currently store
  the conclusive COD and its ICD-11 provenance, but not the other two simple
  fields or DORIS input/result. Existing final-COD authority and analytics
  should continue to read `va_conclusive_cod`.
- WHO ECT and the pinned local ICD API already support ICD-11 selections and
  server-verified code/cluster URI provenance. Reuse those trust boundaries
  for DORIS conditions and the MO final COD.
- Astra's read-only review found an existing HTMX initialization bug in
  `vainitialasses.html` and `vafinalasses.html`: an unrelated swap can reset a
  selected ICD-11 hidden value while the ECT indicator remains green. Fix
  this before relying on the new screens. It also found duplicate codeinfo
  calls during cluster validation and provenance building; combine them
  within an operation if the service work touches that path.

## WHO DORIS components and observed API contract

WHO's web form has administrative data (sex, birth/death dates or estimated
age), Frame A Part I causal lines, Part II contributing conditions, and
Frame B context: recent surgery, autopsy, manner/external cause, fetal or
infant death, and pregnancy. The [WHO certificate format](https://icd.who.int/docs/doris/en/json-format/)
represents Part I as an ordered `Part1` array of line objects, each holding a
`Conditions` array. Each condition can carry `Text`, `Code`,
`LinearizationURI`, `FoundationURI` and `Interval`; Part II is another line
object. Unknown intervals have an explicit representation. The published
exchange-file JSON schema has an **array of certificates** at its top level
and no required properties; the live single-certificate endpoint has a
different top-level request contract. Schema permissiveness is not evidence
that a useful UCOD can be computed from incomplete input.

Read-only synthetic probes against the configured local WHO 2.6.0 image on
2026-09-26 established the following for **this pinned image**:

| Aspect | Observed behavior |
| --- | --- |
| Endpoint | `POST /icd/release/11/2026-01/doris` with `API-Version: v2`, `Accept-Language: en`, `Content-Type: application/json` |
| Request root | One certificate JSON object; sending an array produced HTTP 400 |
| Minimal success | `{"ICDVersion":"ICD11","Part1":[{"Conditions":[{"Code":"BA41.Z"}]}]}` returned HTTP 200, `reject=false`, `code=BA41.Z` and a readable SP1 rule report |
| Accepted forms | Multiple conditions on a Part I line, Part II conditions, one complete code cluster in a condition, and URI-only coded input |
| Missing information | Omitted age and intervals did not prevent the tested coded certificates from processing; empty, text-only and invalid-code certificates returned HTTP 200 with `reject=true` |
| Critical code/URI mismatch | `Code=BA41.Z` paired with a 5A11 URI yielded computed 5A11 and a recoding warning; DORIS did not reject the inconsistent pair |

The [WHO Swagger route](https://id.who.int/swagger/index.html) and the
local image both expose **GET and POST** at
`/icd/release/11/{releaseId}/doris`. GET accepts flat query parameters for
Part I lines A–E, Part II codes/URIs, demographics, intervals and other
context. A synthetic GET with `causeOfDeathCodeA=BA41.Z` computed BA41.Z,
but emitted a sex-value warning when `sex` was omitted; `sex=9` (unknown)
removed that warning. POST accepts the nested certificate JSON and did not
emit that warning for the same minimal case. Use POST for the Help proof and
later clinical integration: it represents each condition and its interval
without flattening the form, and keeps medical text out of query URLs and
routine URL logs. GET remains useful as a small contract smoke check.

The [WHO API documentation](https://icd.who.int/docs/icd-api/DORISSupport/)
names nine response fields. The local image returned:

```json
{
  "stemCode": "BA41.Z",
  "stemURI": "http://id.who.int/icd/entity/1334938734/mms/unspecified",
  "code": "BA41.Z",
  "uri": "http://id.who.int/icd/release/11/mms/1334938734/unspecified",
  "report": "<readable rule explanation>",
  "tabularReport": "<semicolon-delimited rule rows>",
  "reject": false,
  "error": null,
  "warning": null
}
```

The sample illustrates shape, not a response fixture. `code` may be a
multi-stem or postcoordinated expression, while `stemCode` is the selected
stem; `uri` may be a *string of URI components* separated by ` / `, not a
single navigable URL. Reject responses can still be HTTP 200 and carry null
codes/reports plus an error message. The [tabular format specification](https://icd.who.int/docs/icd-api/DORISTabularOutputSpecs/)
describes rule rows but warns that the columns can change; the local image
produced 13 semicolon-separated fields where the published page lists 12.
Display the readable `report`, preserve `tabularReport` raw, and do not build
the first UI around fixed tabular positions. Record the ICD release from the
request/configuration because it is not one of the nine DORIS result fields.

The local Swagger currently marks DORIS pre-release, while WHO ICD API 2.6
release notes describe the API feature as no longer pre-release. Treat this
as a contract-version discrepancy: pin the image, test the exact payload and
response shape, and review the integration before an image upgrade.

### WHO AutoCoding is a separate input aid

The owner's [Swagger reference](https://id.who.int/swagger/index.html) also
shows `AutoCodingSearchResult`. It belongs to
`GET /icd/release/11/{releaseId}/{linearizationname}/autocode?searchText=...`,
not to DORIS. It returns one best text match with `searchText`,
`matchingText`, `theCode`, `foundationURI`, `linearizationURI`,
`matchLevel`, `matchScore`, `matchType` and `isTitle`. A synthetic local query
for “acute myocardial infarction” returned `BA41.Z` with score `1` and WHO
URIs. A high score is a terminology match, not a medical or causal
determination. AutoCoding may later suggest a code for a condition the MO
typed, but the MO must select/confirm it and the server must verify it before
DORIS processing. This is distinct from DORIS's nine-field
`UnderlyingCauseOfDeath` result and remains outside automatic form filling
in the first Help proof.

The mismatched-code probe makes server-side code/URI agreement a mandatory
boundary, even when the browser used WHO ECT. Prefer sending one
server-verified representation per condition; if both code and URI are sent,
compare each to fresh WHO codeinfo before DORIS receives the certificate.

### Mapping to the VA workflow

| Source or output | DigitVA use |
| --- | --- |
| MO-entered Part I/Part II and known context | Editable DORIS form; retain the exact ordered certificate submitted for processing |
| ECT code, text and URI per condition | Verify on the server; construct WHO `Conditions` entries without translating cluster separators into causal relationships |
| DORIS `code`, `stemCode`, `uri`, `stemURI` | Show the computed underlying cause; store as DORIS output, not as the MO final COD |
| DORIS `report`, `tabularReport`, `warning`, `error`, `reject` | Show readable rationale/status; retain raw result for review; never treat HTTP 200 alone as success |
| MO's final underlying ICD-11 selection | Validate independently; save in existing `va_conclusive_cod` with provenance; this alone controls final authority and VA reports |

Two official-source differences need a test in the Help proof: the web guide
describes Part I lines a–d while the current web workspace and local GET
Swagger expose line E; the published JSON schema calls one fetal/infant
measurement `BirthHeight` where the format description calls it
`BirthWeight`. Do not infer either limit or field mapping from the UI alone;
confirm accepted API behavior before copying these controls into VA coding.

## Data and migration design

One additive migration, chained from the committed head at implementation
time (currently `d9e0f1a2b3c4`):

1. `va_project_master.masked_cod_required` Boolean, not null, default true.
2. `va_project_master.cod_entry_mode` constrained to `simple` or `doris`, not
   null, default `simple`. Validate `doris` only with masking off and
   `icd_classification='icd11'` in the admin service and database where
   practical.
3. Add nullable immediate COD and associated-conditions fields to coder and
   reviewer final assessment tables. Existing rows remain null; the existing
   `va_conclusive_cod` remains the final underlying COD.
4. Add nullable `doris_certificate`, `doris_result` and `codedit_result`
   JSONB to both final assessment tables, plus an entry-mode snapshot so
   historical rows remain interpretable if a project's setting changes.

Do not rewrite previous CODs or synthesize first assessments. Existing
masked rows retain their source-initial links. New unmasked final rows have
no source-initial link. Define explicit size limits for the JSON fields and
retain the ICD release, computed code/URI, rationale, warning/reject/error
status, and processing time. Only the human final COD and its verified
provenance feed existing authority and reporting. Exports can present the
DORIS result as a separate column without substituting it for the MO COD.

Prevent setting changes while coder or reviewer allocations are active.
Changing a project later affects new sessions only and never mutates saved
assessments. Recode follows the current project setting, with prior episodes
left intact.

## Implementation packages and order

### 0. Public Help proof of DORIS and CoDEdit with the local WHO image

Build this milestone first and review its working result before beginning
project settings or clinical workflow integration. Add a public, anonymous
`/help/doris-demo` page linked from the public ICD-11 Help browser. It is an
interactive, non-persisting demonstration: enter a WHO-style Part I chain
(including multiple conditions per line), optional Part II, available
intervals and context; choose each ICD-11 condition with the integrated WHO
ECT; send the same certificate to DORIS and CoDEdit. Show the DORIS-computed
UCOD, full expression/URI, rationale, warnings and rejection separately from
CoDEdit's completeness/consistency report and issue IDs. Include a small
synthetic example that can be loaded without using a real VA submission.
The page should explain that DORIS applies coding rules and CoDEdit flags
possible certificate issues; neither validates clinical facts.

The Help page must call a bounded, rate-limited, same-origin DigitVA endpoint
which sends the request server-side to the existing `icd_api_service` image
(`whoicd/icd-api:2.6.0`, `enableDoris=true`, MMS 2026-01). No browser request
should depend on `127.0.0.1:8382`: that address is the *visitor's* computer
for a remote visitor. The existing `/help/icd-codes/search-demo` uses that
loopback address for its ECT comparison and is role-gated; the public DORIS
proof therefore needs an intentionally narrow public ECT path or equivalent
bounded same-origin search, not reuse of a submission-scoped proxy. Permit
only the WHO resources and certificate fields needed for this demo. Enforce
body/response limits, no redirects, short timeouts, rate limits and CSRF on
processing. Do not write entered conditions, API outputs or IP-linked search
content to the database, analytics or application logs. Show unavailable and
rejected responses without pretending a UCOD was computed.

Expected touch points for this phase are `app/routes/help.py`, a new Help
template under `app/templates/help/pages/`, a narrow demo API blueprint
registered in `app/routes/api/__init__.py`, the fixed-target WHO client in
`app/services/who_icd_api.py` or a small DORIS adapter beside it, and focused
Help/API tests. Keep the form adapter reusable by the later clinical route;
the public and clinical authorization boundaries remain separate.

Exit gate: exercise a synthetic certificate against the running local image
through the *public page*, confirm DORIS code/rationale and CoDEdit issue
IDs match direct WHO API responses, test multiple conditions, a cluster and
unknown/missing optional data, then inspect browser network requests and logs. The owner can
review this proof before the clinical workflow packages start. This phase
needs no project-setting or assessment-table migration.

### 1. Policy baseline and existing ICD-11 selection defect

Before behavior changes, add the settled rules to `docs/policy` and update
the current-state documents. Repair the HTMX value reset and verify that the
visible ECT selection matches the submitted hidden value. This is a
prerequisite to using ECT in either unmasked form.

### 2. Project settings and persistence

Add the migration, model fields, admin create/update/read controls, defaults,
constraints, and active-allocation guard. Update
`app/models/va_project_master.py`, both final-assessment models,
`app/routes/admin.py`, the project admin templates, and focused tests. A
fresh project can choose either valid unmasked mode; existing projects stay
masked + simple after migration. Run `flask db heads` before and after.

### 3. Clinical DORIS and advisory CoDEdit service and guarded process API

Reuse the bounded local WHO client and certificate adapter proved by the
public Help milestone. Add clinical allocation and project-mode checks before
this code can process submission data.
Build the WHO JSON certificate from the MO form; validate bounded structure,
ordering, text lengths, codes/clusters, and matching URI provenance. Validate
certificate conditions against WHO codeinfo, but apply DigitVA's local COD
selectability policy only to the MO's final underlying choice. Implement a
CSRF-protected process endpoint requiring the active coder or reviewer
allocation and a valid unmasked ICD-11 DORIS project. Keep browser requests
same-origin; do not expose the WHO service or raw certificate in logs.

Normalize successful, rejected and unavailable DORIS outcomes. Run CoDEdit
on the same certificate and show its findings as **advisory only**: missing
VA information or a CoDEdit warning does not block the MO's final COD.
A failed DORIS run
does not block human finalization. On save, use the result for the current
certificate: reprocess if the input changed since the displayed result, and
do not silently save a stale computed cause. Keep the MO's final code
validation independent of DORIS availability.

### 4. Coder and reviewer screens and saves

Route both roles by project settings. For unmasked simple, show SmartVA
immediately and save the three fields directly to the final assessment. For
unmasked DORIS, render the editable Part I/Part II form, present the computed
cause/rationale and separate advisory CoDEdit findings, then capture the MO's
final underlying code. Reviewer
entry also shows coder COD and SmartVA immediately. Masked simple screens
and two-step saves remain unchanged. Preserve NQA, Social Autopsy,
allocation release, audit events, recode, demo expiry, payload-version
checks, and final-COD authority.

### 5. Documentation and rollout

Update `docs/current-state` for project settings, data model, workflow,
runtime dependency and failure behavior. Update help text so "Step 1/Step
2" appears only for masked projects. Update `handoff.md` after verification.
Roll out the additive migration with the defaults first; enable unmasked
simple in a test project, then unmasked DORIS in an ICD-11 test project.
Existing projects must require an explicit admin setting change.

## Verification gates

- Migration upgrade/downgrade and a single committed head; historical COD
  rows and default project behavior unchanged.
- Admin authorization, CSRF, valid combinations, and an active-allocation
  conflict on setting changes.
- Coder and reviewer tests for all three valid combinations. Unmasked saves
  produce one final row and no first row; SmartVA and coder COD visibility
  follow the table above; final authority and bucket inputs remain human.
- Simple form tests cover three fields and ICD-10/ICD-11 validation.
- DORIS and CoDEdit tests cover multiple conditions on one line, Part II, clusters,
  missing optional data, warning, rejection, timeout, malformed or oversized
  response, changed input, and a human final COD different from DORIS.
- Recode, demo expiry, payload changes, NQA/Social Autopsy and allocation
  behavior remain correct; the ECT hidden-value reset has a regression test.
- The public Help demo passes its separate exit gate before clinical work;
  its anonymous process route is rate-limited and non-persisting.
- One local-container DORIS smoke with a non-sensitive example, followed by
  focused Docker pytest on a dedicated test database, Ruff, template
  compilation, `git diff --check`, and the full Docker suite. A read-only
  code-quality audit reviews the integrated diff before commit and push.

## Risks and limits

WHO DORIS applies mortality selection rules to an MCCD-like cause chain;
DigitVA's VA information may be incomplete. Show its rationale and warnings
as guidance, preserve the human conclusion separately, and never imply that
DORIS validated facts absent from the interview. CoDEdit findings remain
advisory and cannot veto the MO's final COD. The first release has no
automatic VA-to-certificate inference or event graph. Those can be considered
after the MO form is exercised. The
public proof adds an anonymous endpoint, so request bounds, abuse controls
and absence of clinical-data persistence are release gates for that phase.

## References

- `docs/policy/icd11-ect-production.md`
- `docs/policy/coding-workflow-state-machine.md`
- `docs/current-state/workflow-and-permissions.md`
- `docs/planning/icd11-coding-screen-integration-plan.md`
- [WHO DORIS certificate JSON format](https://icd.who.int/docs/doris/en/json-format/)
- [WHO DORIS API output](https://icd.who.int/docs/icd-api/DORISSupport/)
- [WHO CoDEdit output](https://icd.who.int/docs/icd-api/CODEDITTabularOutputSpecs/)
- [WHO ICD API Swagger](https://id.who.int/swagger/index.html)
- `docs/kb/doris-icd-api-and-va.md` (source and local-probe knowledge base)
