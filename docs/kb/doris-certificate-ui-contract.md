---
title: DORIS Certificate UI and API Contract for DigitVA
doc_type: kb
status: active
owner: engineering
last_updated: 2026-09-26
---

# DORIS Certificate UI and API Contract for DigitVA

## Status and intent

This is the shared certificate and interaction contract for the public Help
proof and clinical coder/reviewer editors. Both current editors use plain
JavaScript with the existing vendored Mermaid and WHO ECT assets. A future
mobile app implements the same state, events and JSON API contract in its own UI. WHO
ECT is a browser-only picker, not the cross-platform contract. WHO's DORIS
and CoDEdit engines remain in the pinned local ICD API; DigitVA does not
reimplement WHO mortality selection rules.

The [observed WHO web behavior and request/response shape](doris-web-behavior-and-api-trace.md)
provides evidence. The [project workflow plan](../planning/project-cod-masking-doris-plan.md)
sets when this UI appears and what is saved. The
[parallel HTML/JSON API plan](../planning/coder-web-and-api-contracts.md)
sets authorization and migration boundaries. All paths in this document
are repo-relative. The implemented routes are recorded below; future mobile
endpoints remain proposals.

## Component boundaries

| Boundary | Responsibility |
| --- | --- |
| `CertificateEditor` | Hold the unsaved certificate in browser memory; render applicable questions; manage Part I/II condition arrays, order, one interval per line and code selections; track input revision |
| `ConditionPicker` | Search ICD-11 by term or code, distinguish a complete code/cluster from a separate condition, return selection with code, title and WHO URI provenance |
| `DorisResults` | Show DORIS computed stem and complete code/URI, report, warning, error and rejection; CoDEdit report/issue IDs; raw and derived rule views |
| DigitVA server | Validate bounds, authorization and code/URI agreement; call the fixed local WHO API; return processor results tagged to exact input; persist only in clinical workflow |
| WHO ICD API | Return terminology and codeinfo, CoDEdit checks, and DORIS mortality-rule selection |

Web can implement these as React views, but the contract is the certificate
JSON and state transitions, not React props or DOM events. Public Help has
no clinical record or final MO COD. The clinical unmasked DORIS screen adds
case authorization and the MO's **separate final underlying COD selection**.
Edits stay in the browser form until final save; there is no server-side
clinical draft or preview persistence.

## Certificate data contract

The editor's process payload contains a **single** WHO death-certificate
object and a client revision outside it:

```json
{
  "schema_version": 1,
  "client_revision": 7,
  "certificate": {
    "ICDVersion": "ICD11",
    "AdministrativeData": {"Sex": 1, "EstimatedAge": "P44Y"},
    "Part1": [
      {"Conditions": [
        {
          "Text": "Tuberculous otitis media",
          "Code": "1B12.2&XA0G74",
          "LinearizationURI": "http://id.who.int/icd/release/11/2026-01/mms/883140666 & http://id.who.int/icd/release/11/2026-01/mms/1902897114",
          "Interval": "P14D"
        },
        {
          "Text": "Respiratory tuberculosis, without mention of bacteriological or histological confirmation",
          "Code": "1B10.Z",
          "LinearizationURI": "http://id.who.int/icd/release/11/2026-01/mms/882244568/unspecified",
          "Interval": "P14D"
        }
      ]}
    ],
    "Part2": {"Conditions": []},
    "ICDMinorVersion": "2026-01"
  }
}
```

This is a **synthetic structure test**, not a clinical causal claim. A
`Part1` array entry is one causal line. Its `Conditions` array can have
multiple independent conditions. `1B12.2&XA0G74` is one complete ICD-11
expression and one condition, with two URI components. Never split an `&`
or `/` inside a selected expression into extra conditions or “due to”
arrows. Preserve condition order, line order, the chosen text, exact full
code/cluster, release and canonical URI expression. The editor collects one
interval per Part I line and one for Part II, then serializes it onto every
condition on that line in WHO JSON. The server rejects differing intervals
within a line. Store the server's
verified provenance with each clinical selection. A browser or mobile
client may not assert that its own code/URI pair is verified.

Send both `Code` and `LinearizationURI` only after the server resolves the
selected complete expression with pinned-release WHO codeinfo and verifies
that they agree; reject a mismatch before DORIS, since WHO may silently favor
the URI. Set `ICDMinorVersion` to the pinned release. Preserve both the
release-pinned selected URI and the release-free URI returned by DORIS.
Compare the computed cause with the MO's final choice by resolving both
complete code expressions under the same release, rather than comparing URI
strings with different path forms. Do not strip a release path and assume
that the resulting URI identifies the same expression.

Other fields follow WHO's [certificate exchange format](https://icd.who.int/docs/doris/en/json-format/):

- `AdministrativeData`: sex, dates or estimated age.
- `Part1[]` and `Part2.Conditions[]`: each condition's `Text`, `Code`,
  `LinearizationURI`, optional `FoundationURI`, and `Interval`.
- `Surgery`, `Autopsy`, `MannerOfDeath`, `FetalOrInfantDeath`, and
  `MaternalDeath`: only applicable known facts. The exact field inventory,
  enum values and the observed `BirthWeight`/`BirthHeight` discrepancy are
  recorded in the web-behavior KB.

Unknown clinical information stays unknown. Omit unknown fetal/infant
measurements; `9` means unknown only for the documented enumerated fields.
WHO permits `""`, `"P"` or
`"PT"` for an unknown interval. An uncoded text condition may be entered,
but the editor must warn that DORIS may reject it; it must not invent a
code. Public Help examples may populate the editor but never become
precomputed processor responses.

## UI behavior and state transitions

| Event | Required behavior |
| --- | --- |
| Load example / start blank | Replace the current unsaved browser form; new blank editors show three Part I lines, while loaded certificates keep their stored line count; examples are synthetic and editable; no clinical persistence in Help |
| Add/remove/reorder Part I line | Update ordered `Part1[]`; show the “due to” relationship between adjacent lines; do not infer extra causal edges among conditions on the same line |
| Add/remove condition | Keep each selected complete expression as one removable item; allow several items in one line and in Part II |
| Enter interval | Show a value and time-unit selector after each line's code entry; convert single-unit answers to ISO 8601 for every condition on that line; preserve an existing ISO value until the coder edits it; omit unused blank lines from the request |
| Search by term or code | Show compact rows with code and plain title, inline actions, relevant match and any coding/postcoordination detail; do not render WHO-provided highlight HTML unsanitized; indicate incomplete/truncated results |
| Select code | A guided picker may assemble a stem and WHO-allowed extension choices; retain the complete expression and URI; call server selection-check before marking the chip verified; keep the typed text separate from the selected canonical title |
| See in hierarchy | Show the selected stem within its WHO ancestor path, with bounded sibling and child navigation; keep the selected expression unchanged until the user explicitly confirms a code |
| Edit any input | Increment `client_revision`; clear the displayed DORIS/CoDEdit results and, in clinical coding, clear the selected final UCOD and disable Save |
| Process | Send the current bounded certificate to both processors through DigitVA; show independent loading/error/reject states; accept the response only if its echoed `client_revision` matches the editor's current revision. The server returns a signed process token for clinical finalization. |
| Select and confirm final UCOD (clinical only) | After a current Process result is visible, the MO independently chooses a server-verified complete code/cluster; DORIS does not populate or lock this field. Enable Save only while the certificate is unchanged. |

Use semantic labels, keyboard-operable selection and removal, visible
status/error text, and a mobile-width layout. Do not show hidden fields as
required. When a parent answer makes follow-ups inapplicable, exclude them
from the processed certificate and make the effect on already entered
answers clear. Confirmed WHO behavior: male sex makes pregnancy questions
inapplicable; female sex permits pregnancy status; pregnancy “Yes” enables
timing and contribution. Surgery and external-cause follow-ups remained
visible in a limited WHO probe, so their exact UI rules need testing before
claiming parity. Clinical relevance can guide DigitVA's conditional UI, but
it must not manufacture answers.

## Terminology interaction contract

The existing authenticated WHO ECT proxy is case-scoped and already checks
selected final COD values. The Help editor needs its own bounded public
ECT proxy and **condition** selection-check; the clinical editor needs
active allocation and project checks. Both use one shared server
terminology/provenance service. Final-underlying-COD selectability is checked
only for the MO's final COD, not for every certificate condition.

The observed WHO web term input called MMS `search` with `q=<term>%` and
search flags, while a code prefix called `codeinfo?...flexiblemode=true` and
then fetched an entity title. The web displayed a list and inserted a
removable code chip. Our browser implementation may use ECT for the
picker while matching this surrounding interaction. The future mobile
picker calls a normalized DigitVA terminology API backed by the same
local WHO release; it does not call ECT JavaScript or WHO directly. Define
its response with at least `code`, plain `title`, full `uri`, release,
matching text, postcoordination capability and truncation/paging status.
Use public `POST /api/v1/doris-demo/terms` and `/codeinfo` for Help, and
authenticated `POST /api/v1/doris-clinical/terms/{sid}` and
`/codeinfo/{sid}` for clinical coding. A future mobile
or inline clinical picker. Both boundaries use the same normalized JSON
schema, though authorization and rate limits differ. A terms request is
`{"schema_version":1,"query":"diabetes","limit":20,"cursor":null}`;
the response is `{"schema_version":1,"items":[{"code":"...","title":"...","uri":"...","release":"2026-01","matching_text":"...","postcoordination":false}],"truncated":false,"next_cursor":null}`.
A codeinfo request is `{"schema_version":1,"code":"1B10.Z"}` and its
response is `{"schema_version":1,"item":{"code":"...","title":"...","uri":"...","release":"2026-01","postcoordination":false}}`.
`query` is 2–80 characters, `limit` is 1–20, `code` is at most 128
characters, and `cursor` is opaque. No code or query goes in a URL. The Help
editor exercises these responses even if it also shows WHO ECT. Freeze
errors, pagination and expression handling in phase-0 contract tests. Access
logs must omit query strings for the ECT GET proxy.
Help JavaScript sends its CSRF token on these normalized lookup POSTs,
`selection-check` and `process`. Only the read-only ECT proxy POST is exempt
because the ECT widget cannot attach DigitVA's token.
Search text and selected codes must not go to WHO analytics or DigitVA's
clinical telemetry from public Help.

The guided postcoordination and hierarchy APIs are normalized DigitVA
contracts backed by the pinned WHO MMS release. Public routes use
`/api/v1/doris-demo/postcoordination`, `/postcoordination-options`, and
`/hierarchy`; clinical routes use the same suffixes under
`/api/v1/doris-clinical/` with `/{sid}`. All are CSRF-protected POSTs.
`postcoordination` accepts `{"schema_version":1,"code":"1B12.2"}` and
returns the verified stem plus WHO-ordered axes. Each axis exposes its name,
required flag, exact WHO multiple-value rule, and bounded root options with code,
plain title, release-pinned URI, and `has_children`. An options request
passes the stem code, axis name, and a release-pinned parent option URI to
load bounded direct children. Each option also carries its root `block_uri`,
so `AllowedExceptFromSameBlock` permits choices from separate blocks but
replaces a conflicting choice in the same block. Hierarchy returns an ancestor path and bounded
sibling/child choices for the selected stem. Limits and errors are explicit;
the browser never assumes absent data means that a WHO axis is optional. A
truncated choice set disables guided selection; a complete expression can be
selected directly after the server check.
The UI shows mandatory axes and may add a stem alone only when all required
axes are satisfied. It assembles X extension codes with `&` and additional
stem codes with `/`, in WHO axis order, then sends the complete code and URI
expression through `selection-check`. Both forms remain one condition.

## Processing API contract

| Context | Route | Authorization and effect |
| --- | --- | --- |
| Public Help | `POST /api/v1/doris-demo/process` | Anonymous, rate-limited, CSRF-protected browser request using a token issued by the Help page; bounded current certificate; no database/log/analytics retention of input or output |
| Clinical coder/reviewer | `POST /api/v1/doris-clinical/process/{sid}` | Active allocation, role/project/classification/payload checks; preview only, no final COD write |
| Clinical final save | Mode-specific case finalization | Rebuild and verify exact certificate server-side, obtain or validate server-trusted processing result, save input/results and MO final COD separately |

The Help response has this semantic shape, covered by API contract tests:

```json
{
  "schema_version": 1,
  "client_revision": 7,
  "icd_release": "2026-01",
  "certificate_digest": "server-computed-digest",
  "result_digest": "server-computed-result-digest",
  "doris": {"status": "completed", "result": {"code": "1B10.Z", "stemCode": "1B10.Z", "uri": "...", "stemURI": "...", "report": "...", "tabularReport": "...", "reject": false, "error": null, "warning": null}},
  "codedit": {"status": "completed", "result": {"report": "...", "tabularReport": "...", "issueIds": ""}}
}
```

`certificate_digest` is SHA-256 of the server-normalized certificate JSON
with sorted object keys, compact separators and UTF-8 encoding.
`result_digest` uses the same encoding over the ICD release, WHO image digest,
both processor statuses and their returned result objects; it excludes timing
and transport metadata. The client treats both as opaque values. The clinical
response also includes a short-lived `process_token`, signed by the server,
binding both digests to the case, active allocation, payload version, ICD
release and WHO image. A Help response has no token or clinical authority;
neither context stores a draft or preview in the database.

Statuses distinguish `completed`, `rejected`, `timeout`,
`malformed_response` and `unavailable` for each engine. Invalid input is a
request-level `422 INVALID_INPUT` error, before either engine is called.
Malformed JSON is `400 MALFORMED_JSON`. The error envelope is
`{"schema_version":1,"error":{"code":"INVALID_INPUT","message":"...","fields":[{"path":"certificate.Part1[0].Conditions[0].Code","message":"..."}]}}`;
messages never echo medical text. Public capacity must support five parallel
Process submissions during training; a bounded queue or `429 PROCESS_BUSY`
applies only beyond that capacity.
CoDEdit has no
`reject` field: its success or failure comes from the HTTP status and response
validation. Treat `issueIds` as an opaque WHO value; the current image has
returned strings, but multiple-issue separators and future response types
are not frozen. A single processor failure returns HTTP 200 with the other
processor's status; failure of both returns HTTP 503 with both statuses.
WHO HTTP 200 plus `reject=true` means no reliable computed UCOD. A CoDEdit
finding is advisory. A DORIS-only failure need not block the clinical MO
final COD if independent WHO codeinfo validation still works; loss of the
whole WHO ICD API prevents existing ICD-11 provenance validation and must
fail final save closed. Neither client nor UI may submit a DORIS result as
an authoritative final cause. The final request resubmits the displayed
DORIS/CoDEdit outputs, but the server accepts them only when their digest
matches its signed `process_token`. Clinical finalization also compares the
submitted certificate digest to the certificate last processed. If the form
changed, reprocess the submitted certificate and return
`409 DORIS_CERTIFICATE_CHANGED` with fresh results, a fresh token and a
prompt to review and reconfirm the final UCOD. Save nothing on that request.
If certificate and result digests match, save without rerunning WHO. Only the
confirmed final certificate, verified DORIS/CoDEdit outputs and human UCOD
are persisted.
Changed processor outputs return `409 DORIS_PROCESS_MISMATCH` and require
fresh processing; they are never saved.
An expired or invalid token returns `409 DORIS_PROCESS_EXPIRED`; the MO must
process the form and confirm the final UCOD again.

## Result views

1. Show the computed **stem** and complete `code`/`uri` separately; the
   complete result may contain `&` and `/` components. Show `reject`,
   `warning` and `error` even when HTTP status is 200.
2. Show the readable DORIS rationale and CoDEdit `report`/`issueIds`
   beside the certificate, with explicit “no issues reported” when empty.
   Label verified CoDEdit IDs using WHO's published ID specification; retain
   the raw value and do not split an unverified multi-issue encoding.
3. Keep raw `tabularReport` available. Derive a rule table, Mermaid flow and
   sequence diagram only when there are parseable rows. The diagrams show
   WHO **rule execution**, not clinical causal arrows in Part I.
4. Parse against the pinned report version; bound rows and graph size;
   escape labels and use Mermaid strict security settings. If parsing or
   rendering fails, preserve the readable and raw reports and show a
   visualization error, without changing DORIS status.

The [WHO visualization sample](https://github.com/ICD-API/ICD-API-DORIS-Samples)
proves these derived views are feasible on the pinned local image. Its
source is not copied because the repository has no declared license.

## Acceptance cases before clinical reuse

- Six synthetic Help examples: adult, neonatal death, child with an
  advisory CoDEdit issue, maternal, stillbirth, and TB with a simple stem
  plus a stem/extension expression on one Part I line.
- Blank-start and edited-example processing, term search, code-prefix
  search, full cluster selection, multiple conditions, line order and
  conditional visibility.
- Uncoded text and incomplete VA information, DORIS rejection, CoDEdit
  issue, independent processor failure, WHO outage and a delayed response
  arriving after another edit.
- Exact code/URI agreement on every selected condition and the independent
  final MO field; accessible web interaction and mobile-width layout.
- Clinical edit clears both displayed processor result and chosen final UCOD;
  Save remains disabled until fresh processing and confirmation. A forged or
  raced final request with changed certificate returns 409 and fresh results
  without saving; an expired token also saves nothing.
- Five simultaneous public Process submissions complete while clinical
  requests remain responsive; CSRF rejects unprotected application POSTs.
