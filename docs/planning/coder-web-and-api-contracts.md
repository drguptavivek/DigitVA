---
title: Coder Web and JSON API Contracts
doc_type: planning
status: proposed
owner: engineering
last_updated: 2026-09-26
---

# Coder Web and JSON API Contracts

## Scope and status

This is a **proposed contract**, not a list of implemented endpoints. It
covers the coder journey from allocation/opening a VA form through reading
the submission, notes and quality checks, COD entry, finalization or Not
Codeable. The public DORIS Help proof has its own anonymous API boundary.
The full reviewer journey remains outside this API migration. The reviewer
DORIS process and final-save routes are included here because the shared
certificate and result contract must cover both roles.
The implementation sequence is in
`docs/planning/coder-api-first-workflow-plan.md`; DORIS product decisions are
in `docs/planning/project-cod-masking-doris-plan.md`.
The [certificate UI contract](../kb/doris-certificate-ui-contract.md) defines
the shared data and state model for the Help, web and future mobile clients.

The planned coder web client is React. Flask/Jinja and HTMX remain as
compatibility routes during incremental migration; the React client consumes
the proposed JSON APIs. A future mobile client should consume the same
domain contract, without depending on HTML fragments, WHO ECT DOM callbacks,
or browser hidden inputs. React web components that require the DOM,
including WHO ECT, are not directly reusable in a native mobile renderer.
DigitVA owns the DORIS certificate editor and results views. The WHO web
application supplies a behavior reference; the local WHO ICD API supplies
terminology, CoDEdit and DORIS processing. The same certificate schema is
used by public Help and, later, authenticated clinical coding.

## Existing web/HTMX contract to preserve during migration

| Current surface | Request/response contract | Important behavior to preserve |
| --- | --- | --- |
| Coder dashboard | Existing `/api/v1/coding/allocation`, `/available`, `/stats`, `/history`, `/projects` JSON APIs; HTML pick/recode actions also remain | Role and project/form eligibility, random/pick/demo/recode allocation |
| Enter or resume form | `app/routes/coding.py` builds an HTML case shell through `render_va_coding_page()` | Active allocation, navigation metadata, demo/recode handling, one queued open-payload repair |
| Category and assessment panels | `GET /vaform/<sid>/<partial>` returns HTML fragments for HTMX swaps | Per-case access, active payload, category rendering, existing PII redaction, permitted attachments and SmartVA timing |
| Coder Step 1 | `POST /vaform/<sid>/vainitialasses` through the current form route | Current masked flow's initial assessment and state transition |
| Coder final COD | `POST /vaform/<sid>/vafinalasses` through the current form route | ICD validation/provenance, NQA/Social gates, audit, final authority, allocation release and cache effects |
| Notes and Not Codeable | Other `POST /vaform/<sid>/<partial>` branches | User note, local terminal Not Codeable transition and best-effort ODK update |

These current contracts are implemented across `app/routes/api/coding.py`,
`app/routes/coding.py`, `app/services/coding_service.py`, and
`app/routes/va_form.py`. Keep them working until the corresponding JSON API
and web client pass parity tests. Both the HTML route and JSON route must
call the **same service operation** for each mutation; they must not contain
separate copies of COD, allocation or authorization rules.

## Proposed JSON contract, `/api/v1/coding`

All case routes below are **new proposals**. `sid` is the opaque DigitVA
submission identifier already used by the current routes; it is not an ODK
form ID or ODK submission key. The server derives project mode, language,
allowed actions and evidence visibility from the authenticated user and
current allocation. The client cannot set its own `masked_cod_required`,
`cod_entry_mode`, role or workflow state.

| Method and path | Response or request responsibility |
| --- | --- |
| Existing `GET /allocation`; `POST /allocation` | Keep current fields; add the existing allocation ID, current workflow state and payload version, project/mode and capabilities without breaking current dashboard consumers; do not invent an expiry value |
| `GET /cases/{sid}` | Case bootstrap: masked metadata, allocation ID and workflow state, payload version, server-derived mode, category manifest, completion flags, permitted links/actions |
| `GET /cases/{sid}/categories/{category_code}` | Semantic, redacted fields and authorized attachment descriptors for one category; no raw ODK payload or local path |
| `GET /cases/{sid}/cod-context` | ICD classification/search links, current human assessments, available SmartVA guidance, NQA/Social completion; omit evidence that the current phase must mask |
| `GET /cases/{sid}/note`; `PUT /cases/{sid}/note` | Read or replace the current coder's note under active case access |
| Existing NQA/Social and ICD search APIs | Link from bootstrap; keep their services and authorization, standardize errors without duplicating endpoints |
| `PUT /cases/{sid}/initial-assessment` | Masked mode only: immediate, antecedent and other conditions; server-side code/provenance validation |
| `POST /cases/{sid}/doris/process` | Unmasked ICD-11 DORIS mode only: preview one bounded certificate through DORIS and CoDEdit; no final COD write |
| `POST /cases/{sid}/finalize` | Mode-specific human final entry, current certificate if DORIS mode, independent final-code validation, atomic assessment/workflow/authority/audit update and allocation release |
| `POST /cases/{sid}/not-codeable` | Structured reason and local terminal outcome; report ODK update result separately |

The current dashboard allocation API is an existing API, not a newly
specified route. The new case APIs should be added to its `/api/v1/coding`
namespace. The reviewer process route is
`POST /api/v1/review/cases/{sid}/doris/process`; its final save is
`POST /api/v1/review/cases/{sid}/finalize` and uses the same
certificate and acknowledgement semantics with reviewer-specific
authorization. The reviewer starts from a copy of the coder's saved
certificate when one exists, or a blank certificate otherwise, then edits an
independent browser form. Neither role has a server-side draft endpoint.
Never mutate the coder's certificate through reviewer actions.

### Case bootstrap example

```json
{
  "schema_version": 1,
  "sid": "synthetic-sid",
  "allocation": {"id": "opaque-allocation-id"},
  "workflow": {"state": "coding_in_progress"},
  "payload_version_id": "opaque-version-id",
  "project": {"icd_classification": "icd11", "coding_mode": "unmasked_doris"},
  "allowed_actions": ["read_category", "save_note", "process_doris", "finalize"],
  "categories": [{"code": "narrative", "label": "Narrative", "href": "/api/v1/coding/cases/synthetic-sid/categories/narrative"}],
  "links": {"cod_context": "/api/v1/coding/cases/synthetic-sid/cod-context"}
}
```

The example keys define the intended semantics, not the current database
shape. Masked metadata follows the existing dashboard policy. `coding_mode`
is a server-derived snapshot of the approved project configuration. The
response must not include SmartVA data or hidden coder/reviewer decisions
when the current workflow phase does not permit them.

### Case mutations and conflicts

Every case mutation supplies `expected_payload_version_id`; terminal
mutations also supply `expected_workflow_state` and the active allocation ID.
The server checks these against the active allocation and current case in
the same transaction as the write. If they differ, return `409` with the
current state/version and require a refresh. Repeated terminal requests must
not create a second assessment; after an uncertain network response the
client refreshes `GET /cases/{sid}` to discover the committed outcome.
Document a stronger idempotency-key contract before native mobile retries
or offline queuing are enabled.

`POST /finalize` accepts exactly one mode-specific body:

- `masked_simple`: current Step 1 already saved; final human underlying COD.
- `unmasked_simple`: human immediate COD, underlying COD and optional
  associated conditions as free text, with no artificial Step 1 row. ICD-11
  immediate and underlying selections have separate provenance entries.
- `unmasked_doris`: ordered Part I/Part II certificate, the signed
  `process_token` from its current Process response, plus the MO's
  independent final underlying COD and the DORIS/CoDEdit outputs shown in
  that response. The server accepts those outputs only when their digest
  matches the signed token issued for that exact certificate and release.
An edit clears the displayed result and selected final UCOD in the client
and disables Save until a new Process response is reviewed and the final UCOD
is confirmed again. At final save, verify the signed token and compare the
submitted certificate digest to the one it binds. If they differ, reprocess
the submitted certificate and return `409 DORIS_CERTIFICATE_CHANGED` with the
fresh result and token, asking the MO to review and reconfirm; commit nothing.
If the certificate matches but the submitted processor outputs do not match
the token's result digest, return `409 DORIS_PROCESS_MISMATCH` and require
fresh processing; commit
nothing. When both digests match, do not rerun WHO merely to save. Compare
payload version, workflow state and active allocation again on resubmission.
An expired or invalid process token returns `409 DORIS_PROCESS_EXPIRED` and
requires a fresh Process call and final UCOD confirmation; it saves nothing.
Persist only the confirmed final certificate, server-obtained DORIS/CoDEdit
outputs and human final UCOD, not intermediate forms or process responses.
The changed-certificate response is HTTP 409 with
`error.code="DORIS_CERTIFICATE_CHANGED"`, a plain message that the form was
reprocessed, and `processing` containing the fresh Process response shape
including its new token. The client clears the old final UCOD choice and
requires an explicit new confirmation before another Save request.

The final underlying code is a complete ICD-11 expression when applicable,
with WHO URI provenance checked on the server. In DORIS mode, CoDEdit
findings are advisory. A DORIS/CoDEdit failure does not block a human final
COD if independent WHO codeinfo validation succeeds; a whole WHO API outage
still prevents the existing ICD-11 final-code provenance check.

### Response and error semantics

New APIs return `application/json` and an application `schema_version`.
Use `200` for reads and completed commands, `201` for newly created
allocations, `400` for malformed JSON, `401` for an unauthenticated session,
`403` for insufficient role/form/site/allocation access, `404` for a missing
or concealed case, `409` for stale allocation/workflow/payload, `422` for
field or domain validation, and `503` when a required WHO validation service
is unavailable. Field errors use JSON paths that a web or mobile client can
place beside controls.

```json
{
  "schema_version": 1,
  "error": {
    "code": "STALE_PAYLOAD",
    "message": "This submission changed. Reload before saving.",
    "fields": [],
    "current_state": "coding_in_progress",
    "current_payload_version_id": "opaque-current-version-id"
  }
}
```

The same HTTP response code must mean the same class of outcome for an
HTMX-backed web action and the JSON action. Existing API response bodies
may remain unchanged while new endpoints adopt the common envelope.

## Public DORIS Help API contract

These routes are anonymous and distinct from clinical case APIs:

| Method and path | Contract |
| --- | --- |
| `GET /api/v1/doris-demo/config` | Return application schema version, ICD release, supported fields/limits and the six synthetic `certificate` examples from `resource/doris_help_examples.json`; do not expose saved `observed` results as live outputs |
| `POST /api/v1/doris-demo/process` | Accept `{schema_version, client_revision, certificate}` from the current editor, validate bounds and code/URI agreement, send the same normalized certificate to local DORIS and CoDEdit, and echo the revision with independent live responses, release, input digest and processing status; do not persist certificate or results |
| `POST /api/v1/doris-demo/terms`; `POST /api/v1/doris-demo/codeinfo` | Return the normalized terminology JSON shapes in the UI contract, with public limits and no query or code in the URL; Help JavaScript sends the CSRF token |
| `GET/POST /api/v1/doris-demo/who-api/{resource}` | Allowlist only read-oriented ECT search, entity and codeinfo resources; fixed local WHO target, bounds and rate limits; CSRF-exempt for ECT POST; no submission-scoped proxy |
| `POST /api/v1/doris-demo/selection-check` | Verify a selected complete code/cluster and WHO URI for a certificate condition without applying final-underlying-COD selectability |

The response exposes every DORIS field (`code`, `stemCode`, `uri`, `stemURI`,
`report`, `tabularReport`, `reject`, `error`, `warning`) and every CoDEdit
field (`report`, `tabularReport`, `issueIds`). The Help screen shows the
readable reports and warnings directly and makes raw tabular reports
expandable. It also derives a rule table, flow graph and sequence diagram
from nonempty DORIS `tabularReport`; those are presentation views, not extra
API decisions or persisted clinical data. Parse/render errors must leave the
readable and raw reports available, and any WHO text in HTML or Mermaid
source must be safely escaped. A WHO HTTP 200 with `reject=true` is a rejected DORIS result,
not a successful UCOD. `issueIds` remains an opaque upstream value: the
pinned image has returned strings in current fixtures, but a multi-issue
case must establish its encoding before the UI splits or labels it.
If one processor fails, return its failure status separately from the other
processor's result. CoDEdit has no `reject` field; classify it from the HTTP
status and validated response. A valid request with both processors failing
returns HTTP 503 and two independent failure statuses. Do not substitute
fixture observations or stale prior responses. The public endpoint uses fixed WHO targets, bounded input/output,
timeouts, a total deadline, rate limits and browser CSRF for `process`,
`selection-check`, normalized `terms` and `codeinfo`; it never accepts
arbitrary URLs. The read-only ECT proxy alone is CSRF-exempt because ECT
cannot attach the header. Help issues an anonymous session token for its
protected POSTs. Run the Help page and API on a dedicated same-origin public
service, routed separately from clinical Flask workers, with capacity for at
least five concurrent Process submissions during training.
Examples populate editable form state. Clear or mark the displayed results
stale when that state changes, and discard delayed responses whose input
revision no longer matches the editor. The client compares only echoed
`client_revision`; the server owns certificate and result digests. The
selected condition code or cluster must retain server-verified WHO URI
provenance. The existing
clinical WHO ECT proxy is submission-scoped, so public Help needs a separate
allowlisted proxy and selection check. Certificate conditions are checked
against WHO terminology; DigitVA's final-underlying-COD selectability
policy applies only to the eventual MO final choice. Discard ECT analytics
events locally, as the current authenticated proxy already does.
The Help editor also calls the normalized public terms and codeinfo routes,
which use the same JSON shape as the future authenticated
`POST /api/v1/icd11/terms` and `/codeinfo` intended for mobile clients.
The ECT GET proxy's query strings must be omitted from Gunicorn access logs;
verify WHO container logs do not retain them before release.
The Help page links to the WHO DORIS web application as a separate
interactive reference. There is no automatic data transfer from that
application to DigitVA. Its Save to file control is outside this contract.

The clinical `POST /cases/{sid}/doris/process` shares the certificate schema and WHO
adapter but requires active allocation and project-mode authorization. Its
result includes the certificate input digest and ICD release. Preview
results are display data; the clinical response includes a short-lived
server-signed `process_token` binding certificate and result digests to case,
allocation, payload version, release and WHO image. Final save verifies the
submitted certificate and processor outputs against that token. It only
reprocesses if the certificate has changed, returning fresh results for
reconfirmation rather than saving. No draft or process response is stored
before final save.

## Authentication and client boundary

The web client continues to use Flask-Login session cookies and
`X-CSRFToken` on every state-changing JSON request. Authorization decisions
belong in a shared service used by the HTML and JSON routes, not in the
template or client-provided `actiontype`. Keep per-form, site, project,
language, active-allocation, retired-form and payload-version checks.
Category JSON must apply the same PII redaction as the existing HTML path.
Attachment references must be opaque authorized delivery URLs, not disk
paths. Avoid logging raw certificates or submission payloads.

Native mobile authentication is **not implemented by this contract**.
Before a mobile app can use clinical APIs, add an approved OIDC/OAuth
authorization-code-with-PKCE flow, map identity to existing roles, and
specify token/device lifecycle. A bearer-authenticated request may receive
a narrowly scoped CSRF exemption only after that authentication succeeds;
do not disable CSRF for session-authenticated browser requests. Offline
allocation/sync is a separate decision, not assumed here.

## Parity gate before retiring HTMX mutations

For each action, test the existing HTML/HTMX path and the proposed JSON
path against the same service: authorization, PII visibility, saved rows,
workflow state, authority, audit, allocation release, recode/demo behavior,
NQA/Social gates and error statuses must agree. The existing web route can
then become a thin compatibility adapter. Remove its mutation branch only
after the web client uses the JSON path and browser regression passes.
