---
title: DORIS Certificate UI and API Contract for DigitVA
doc_type: kb
status: proposed
owner: engineering
last_updated: 2026-09-26
---

# DORIS Certificate UI and API Contract for DigitVA

## Status and intent

**Proposed contract; no DigitVA DORIS UI or clinical endpoint exists yet.**
This is the build contract for reproducing the useful behavior of WHO DORIS
inside DigitVA. The web implementation may be React; a future mobile app
implements the same state, events and JSON API contract in its own UI. WHO
ECT is a browser-only picker, not the cross-platform contract. WHO's DORIS
and CoDEdit engines remain in the pinned local ICD API; DigitVA does not
reimplement WHO mortality selection rules.

The [observed WHO web behavior and request/response shape](doris-web-behavior-and-api-trace.md)
provides evidence. The [project workflow plan](../planning/project-cod-masking-doris-plan.md)
sets when this UI appears and what is saved. The
[parallel HTML/JSON API plan](../planning/coder-web-and-api-contracts.md)
sets authorization and migration boundaries. All paths in this document
are repo-relative; all endpoint names below are proposed unless explicitly
called existing.

## Component boundaries

| Boundary | Responsibility |
| --- | --- |
| `CertificateEditor` | Hold one WHO-shaped draft certificate; render applicable questions; manage Part I/II condition arrays, order, intervals and code selections; track input revision |
| `ConditionPicker` | Search ICD-11 by term or code, distinguish a complete code/cluster from a separate condition, return selection with code, title and WHO URI provenance |
| `DorisResults` | Show DORIS computed stem and complete code/URI, report, warning, error and rejection; CoDEdit report/issue IDs; raw and derived rule views |
| DigitVA server | Validate bounds, authorization and code/URI agreement; call the fixed local WHO API; return processor results tagged to exact input; persist only in clinical workflow |
| WHO ICD API | Return terminology and codeinfo, CoDEdit checks, and DORIS mortality-rule selection |

Web can implement these as React views, but the contract is the certificate
JSON and state transitions, not React props or DOM events. Public Help has
no clinical record or final MO COD. The clinical unmasked DORIS screen adds
case context, authenticated draft handling, and the MO's **separate final
underlying COD selection**.

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
          "Interval": "P60D"
        }
      ]}
    ],
    "Part2": {"Conditions": []}
  }
}
```

This is a **synthetic structure test**, not a clinical causal claim. A
`Part1` array entry is one causal line. Its `Conditions` array can have
multiple independent conditions. `1B12.2&XA0G74` is one complete ICD-11
expression and one condition, with two URI components. Never split an `&`
or `/` inside a selected expression into extra conditions or “due to”
arrows. Preserve condition order, line order, the chosen text, exact full
code/cluster, release and canonical URI expression. Store the server's
verified provenance with each clinical selection. A browser or mobile
client may not assert that its own code/URI pair is verified.

Other fields follow WHO's [certificate exchange format](https://icd.who.int/docs/doris/en/json-format/):

- `AdministrativeData`: sex, dates or estimated age.
- `Part1[]` and `Part2.Conditions[]`: each condition's `Text`, `Code`,
  `LinearizationURI`, optional `FoundationURI`, and `Interval`.
- `Surgery`, `Autopsy`, `MannerOfDeath`, `FetalOrInfantDeath`, and
  `MaternalDeath`: only applicable known facts. The exact field inventory,
  enum values and the observed `BirthWeight`/`BirthHeight` discrepancy are
  recorded in the web-behavior KB.

Unknown clinical information stays unknown. WHO permits `""`, `"P"` or
`"PT"` for an unknown interval. An uncoded text condition may be entered,
but the editor must warn that DORIS may reject it; it must not invent a
code. Public Help examples may populate the editor but never become
precomputed processor responses.

## UI behavior and state transitions

| Event | Required behavior |
| --- | --- |
| Load example / start blank | Replace one browser draft; examples are synthetic and editable; no clinical persistence in Help |
| Add/remove/reorder Part I line | Update ordered `Part1[]`; show the “due to” relationship between adjacent lines; do not infer extra causal edges among conditions on the same line |
| Add/remove condition | Keep each selected complete expression as one removable item; allow several items in one line and in Part II |
| Search by term or code | Show code, plain title, relevant match and any coding/postcoordination detail; do not render WHO-provided highlight HTML unsanitized; indicate incomplete/truncated results |
| Select code | Use existing WHO ECT first in the browser; retain complete expression and URI; call server selection-check before marking the chip verified; keep the typed text separate from the selected canonical title |
| Edit any input | Increment `client_revision`; clear or mark DORIS/CoDEdit results stale immediately |
| Process | Send the current bounded certificate to both processors through DigitVA; show independent loading/error/reject states; accept the response only if its echoed revision and digest match current input |
| Select final underlying COD (clinical only) | MO chooses an independently verified complete code/cluster; DORIS guidance does not populate or lock this field automatically |

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
Propose `GET /api/v1/icd11/terms?q=...` and
`GET /api/v1/icd11/codeinfo?code=...` for mobile and any future inline
web picker, with separate anonymous Help and authenticated case access
policies. Freeze query limits, URL encoding for `/` and `&` expressions,
pagination and error envelopes in contract tests before implementation.
Search text and selected codes must not go to WHO analytics or DigitVA's
clinical telemetry from public Help.

## Processing API contract

| Context | Proposed route | Authorization and effect |
| --- | --- | --- |
| Public Help | `POST /api/v1/doris-demo/process` | Anonymous, rate-limited, CSRF-protected browser request; bounded current certificate; no database/log/analytics retention of input or output |
| Clinical coder/reviewer | `POST /api/v1/coding/cases/{sid}/doris/process` and reviewer equivalent | Active allocation, role/project/classification/payload checks; preview only, no final COD write |
| Clinical final save | Mode-specific case finalization | Rebuild and verify exact certificate server-side, obtain or validate server-trusted processing result, save input/results and MO final COD separately |

The Help response should have this semantic shape; actual field names must
be frozen in API contract tests before implementation:

```json
{
  "schema_version": 1,
  "client_revision": 7,
  "icd_release": "2026-01",
  "certificate_digest": "server-computed-digest",
  "doris": {"status": "completed", "result": {"code": "1B10.Z", "stemCode": "1B10.Z", "uri": "...", "stemURI": "...", "report": "...", "tabularReport": "...", "reject": false, "error": null, "warning": null}},
  "codedit": {"status": "completed", "result": {"report": "...", "tabularReport": "...", "issueIds": ""}}
}
```

Statuses distinguish completed, rejected and unavailable for each engine.
WHO HTTP 200 plus `reject=true` means no reliable computed UCOD. A CoDEdit
finding is advisory. A DORIS-only failure need not block the clinical MO
final COD if independent WHO codeinfo validation still works; loss of the
whole WHO ICD API prevents existing ICD-11 provenance validation and must
fail final save closed. Neither client nor UI may submit a DORIS result as
an authoritative final cause. Clinical finalization checks the exact
certificate/digest/release and returns a changed computed result for MO
review before committing.

## Result views

1. Show the computed **stem** and complete `code`/`uri` separately; the
   complete result may contain `&` and `/` components. Show `reject`,
   `warning` and `error` even when HTTP status is 200.
2. Show the readable DORIS rationale and CoDEdit `report`/`issueIds`
   beside the certificate, with explicit “no issues reported” when empty.
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
