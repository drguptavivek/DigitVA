---
title: WHO DORIS, CoDEdit and AutoCoding in DigitVA
doc_type: kb
status: active
owner: engineering
last_updated: 2026-09-26
---

# WHO DORIS, CoDEdit and AutoCoding in DigitVA

## Purpose and evidence boundary

This is the technical knowledge base for the proposed public Help proof and
later VA coding integration. It records WHO's published contracts and
read-only **synthetic** probes made on 2026-09-26 against DigitVA's pinned
local `whoicd/icd-api:2.6.0` image. It does not describe an implemented
DigitVA DORIS workflow. The implementation sequence and decisions are in
`docs/planning/project-cod-masking-doris-plan.md`.

The local Compose profile `icd11` enables DORIS, loads ICD-11 MMS
`2026-01_en`, and disables analytics. The application reaches the image at
`http://icd_api_service`; the host's `127.0.0.1:8382` mapping is for local
evaluation only. A remote visitor's browser cannot use that loopback address
to reach DigitVA's WHO container.

| Component | What it does | What it does not do |
| --- | --- | --- |
| WHO Embedded Coding Tool (ECT) | Helps a person select an ICD-11 code/cluster and URI for each condition | Does not decide the underlying cause |
| WHO AutoCoding | Returns one best terminology match for input text | Does not verify the diagnosis or causal chain |
| CoDEdit | Checks certificate completeness, consistency and code plausibility | Does not choose the final underlying cause |
| DORIS | Applies digital ICD mortality selection rules to a coded certificate and computes a UCOD | Does not establish that the certificate's clinical facts are true |
| SmartVA | Gives algorithmic VA cause guidance from the interview | Does not fill the MCCD chain or make DigitVA's final MO decision |
| Medical officer | Enters or reviews the cause chain and chooses the final COD in DigitVA | Is not replaced by any of the above tools |

WHO describes DORIS as a rule-based aid for selecting one underlying cause
from a medical certificate. Its web UI exposes the applied steps and
warnings. WHO separately describes VA as a means of assigning a *probable*
cause when medical certification is unavailable. These are related sources
of evidence, not interchangeable records. Missing clinical detail in VA is
expected; never invent it to satisfy a digital certificate form.

## DORIS certificate components

WHO's web workspace has Frame A and Frame B:

| Area | Fields in the WHO JSON exchange format |
| --- | --- |
| Administrative data | Sex (`1` male, `2` female, `9` unknown); birth/death dates or estimated age |
| Frame A, Part I | Ordered line objects in `Part1`; each line has a `Conditions` array and may contain multiple conditions |
| Frame A, Part II | `Part2` line object with conditions that contributed but are outside the direct Part I sequence |
| One condition | `Text`, `Code`, `LinearizationURI`, `FoundationURI`, `Interval`; codes may be complete postcoordinated expressions |
| Frame B | Surgery, autopsy, manner/external cause, fetal/infant details, maternal/pregnancy details when applicable and known |

An upper Part I line is represented as due to the line below; conditions on
one line are multiple entries, not successive causal events. Slash and
ampersand separators within an ICD-11 expression describe coding and
postcoordination, not a causal arrow. Preserve line order and condition
order. Unknown intervals have WHO-documented representations `""`, `"P"`
or `"PT"`; do not manufacture a duration. The published schema marks no
properties required, but the engine needs a valid coded condition to return
a computed cause in the tested cases.

Minimal successful **POST body** used against this local image:

```json
{
  "ICDVersion": "ICD11",
  "Part1": [
    {"Conditions": [{"Code": "BA41.Z"}]}
  ]
}
```

This is a synthetic API example, not a suggested clinical certificate. The
exchange-file JSON schema has an array of certificates at its root. The
single-certificate DORIS POST endpoint instead accepted **one object** and
returned HTTP 400 for an array.

The WHO web guide describes Part I a–d; the current public web workspace
shows A–E and local Swagger's GET form accepts A–E. Confirm POST behavior
before setting a fixed line limit in DigitVA. Another source discrepancy:
the published JSON schema says `FetalOrInfantDeath.BirthHeight`, while the
format description and GET Swagger say birth *weight*. Do not map that field
without a version-specific probe.

## DORIS GET and POST

Both methods exist at `/icd/release/11/{releaseId}/doris`. The tested local
path is `/icd/release/11/2026-01/doris`, using headers `API-Version: v2` and
`Accept-Language: en`. POST also uses `Content-Type: application/json`.

GET takes flat query parameters such as `causeOfDeathCodeA` through E,
matching URI parameters, `causeOfDeathCodePart2`, intervals and contextual
fields. A synthetic GET with `causeOfDeathCodeA=BA41.Z` returned the same
computed code as POST, but omission of `sex` produced a warning; `sex=9`
removed it. POST with the minimal body above produced no sex warning.

POST is the planned integration method: it carries each condition's text,
code/URI and interval in nested JSON, and does not put medical text in a
query URL. GET is useful for a compact smoke check, not the full MO form.

## DORIS response shape and interpretation

The `UnderlyingCauseOfDeath` response has nine top-level fields:

| Field | Observed type and use |
| --- | --- |
| `code` | String with the complete computed code or cluster; null on tested rejections |
| `stemCode` | String with selected stem; not a substitute for the complete `code` |
| `uri` | String with computed URI expression; a cluster can contain several URI components separated by ` / ` |
| `stemURI` | String returned by WHO for the selected stem; retain as returned |
| `report` | Readable rule explanation; null on tested rejections |
| `tabularReport` | Semicolon-delimited rule rows as one string; empty on tested rejections |
| `reject` | Boolean indicating failure to select UCOD; check even when HTTP status is 200 |
| `error` | Nullable error text |
| `warning` | Nullable warning text, including cases needing manual review |

The single-code synthetic BA41.Z request returned HTTP 200, `reject=false`,
`code=stemCode="BA41.Z"`, URI strings, and a `report` starting with SP1
selection followed by a full rule trace (SP1, SP6–SP8, M1–M3). An empty,
text-only, or invalid-code certificate returned HTTP 200 with `reject=true`,
null code/URI/report, an empty tabular report, and an error asking for manual
check. A tested multi-condition Part I/Part II certificate returned a
multi-stem cluster and a warning. A complete cluster in one condition and a
URI-only condition were accepted in separate probes. Missing age and
intervals did not prevent *those tested coded cases* from processing.

The `uri` field for a computed cluster is a URI **expression string**, not
one ordinary clickable URL. Keep the full `code` and `uri`; do not truncate
to the first stem. Record the release used for the request separately,
because the nine-field response does not carry an ICD release field.

WHO's tabular report specification lists 12 columns and warns that its
layout may change. The local image produced rows with 13 semicolon-separated
fields, including a trailing `BER` value. Keep the raw `tabularReport` for
review. The first UI can show the human-readable `report` without relying on
fixed tabular column positions.

### Code and URI agreement is a trust boundary

In a deliberately inconsistent synthetic condition, `Code=BA41.Z` was
paired with a URI for 5A11. DORIS returned 5A11 with a recoding warning,
instead of rejecting the pair. Thus ECT selection alone is not enough: the
DigitVA server must verify the full code/cluster and URI agreement against
the pinned WHO codeinfo before forwarding a certificate. The final MO COD
is independently checked against DigitVA's COD selectability policy.
Certificate conditions can legitimately include codes that are not locally
selectable as *final underlying* CODs, so that final-COD policy should not be
applied indiscriminately to every condition.

## CoDEdit: separate certificate checks

CoDEdit exposes GET and POST at
`/icd/release/11/{releaseId}/codedit`, with the same flat GET or structured
POST certificate choices. The local `DeathCertificateCheckResult` response
contains only `report`, `tabularReport` and `issueIds`. In the pinned image,
all three were **strings**. The official description calls `issueIds` a
“list,” but a synthetic POST returned the comma-separated string
`"BER-CE-2,BER-CE-3"`, not a JSON array, when age and sex were omitted.
Its report recommended completing those fields. The same one-code sample
with `Sex=1` and `EstimatedAge="P52Y"` returned empty strings for all three
fields. Empty strings mean no reported checks in that probe, not proof that
the medical account was complete or clinically correct.

The public [identifier specification](https://icd.who.int/docs/icd-api/DORIS-CODEDIT-IdsListSpecs/)
defines check IDs, including `BER-CE-9` for an inconsistent code/URI pair;
the [tabular specification](https://icd.who.int/docs/icd-api/CODEDITTabularOutputSpecs/)
describes serialized messages and warns that layout can change. CoDEdit
may help the MO spot correctable inconsistencies. Missing data warnings are
expected in VA. The owner decided on 2026-09-26 to show CoDEdit alongside
DORIS in the first public Help proof and later as **advisory only** in the
clinical form. Findings must never block or silently replace the MO COD.

## AutoCoding: separate text-to-code suggestion

The local WHO image exposes
`GET /icd/release/11/{releaseId}/mms/autocode?searchText=...`. Its
`AutoCodingSearchResult` includes `searchText`, `matchingText`, `theCode`,
`foundationURI`, `linearizationURI`, `matchLevel`, `matchScore`, `matchType`
and `isTitle`. For the synthetic phrase “acute myocardial infarction,” the
local image returned `theCode="BA41.Z"`, a matching phrase, WHO URIs and
`matchScore=1`. This is one best terminology match. It must be treated as a
suggestion for a condition the MO entered, not a confirmed diagnosis,
causal relationship, DORIS result, or final underlying COD. Automatic
prefilling and suggestions are deferred from the first Help proof.

## Relationship to DigitVA and the planned sequence

DigitVA already has WHO ECT 1.8 and a fixed-target local ICD API client.
Coder and reviewer final assessments retain a complete ICD-11 expression
and server-verified provenance. They currently do **not** store a DORIS
certificate/result; the existing two-step panel also lacks a general
Part I/Part II chain. The WHO VA source has an MCCD transcript block:
`Id10462`–`Id10473` include certificate availability, Part I text/durations
and contributing conditions. Those fields can later offer editable source
material when a certificate exists, but must not be assumed present or
silently promoted into a new MO assertion.

The owner-approved product direction is:

1. First prove the public Help form against this local WHO image, running
   DORIS and CoDEdit on the same certificate, without saving a VA submission
   or changing project settings.
2. Later add two project settings: masked COD yes/no and final entry mode
   simple/DORIS. DORIS is valid only for unmasked ICD-11 projects.
3. In unmasked simple mode, a coder or reviewer makes one human final entry
   with immediate COD, underlying COD and associated conditions.
4. In unmasked DORIS mode, the MO enters the causal chain, sees DORIS's
   computed underlying COD and rationale plus advisory CoDEdit findings,
   then selects one final underlying COD. Save certificate, DORIS result,
   CoDEdit result and MO final COD distinctly. A
   rejected or unavailable DORIS run must not invent a result or block the
   human final COD decision.
5. Unmasked reviewers see the coder COD and SmartVA before their one final
   review. Masked projects retain the current blind first-entry workflow.

The public Help endpoint requires bounded input and output, rate limits,
CSRF for processing, fixed local WHO target, and no retention or logging of
entered medical text. The clinical endpoint later needs active allocation,
role, project-mode and payload checks as well. These are separate access
boundaries even if they reuse one certificate adapter.

## Sources and local evidence

- [WHO DORIS overview](https://icd.who.int/docs/doris/en/)
- [WHO DORIS web components](https://icd.who.int/docs/doris/en/doris-web/)
- [WHO certificate JSON format](https://icd.who.int/docs/doris/en/json-format/)
- [WHO certificate JSON schema](https://icd.who.int/docs/doris/en/files/electronicDeathCertificateSchema.json)
- [WHO DORIS and CoDEdit API support](https://icd.who.int/docs/icd-api/DORISSupport/)
- [WHO DORIS tabular output](https://icd.who.int/docs/icd-api/DORISTabularOutputSpecs/)
- [WHO CoDEdit tabular output](https://icd.who.int/docs/icd-api/CODEDITTabularOutputSpecs/)
- [WHO CoDEdit identifiers](https://icd.who.int/docs/icd-api/DORIS-CODEDIT-IdsListSpecs/)
- [WHO ICD API Swagger](https://id.who.int/swagger/index.html)
- [WHO ICD-11 Reference Guide](https://icdcdn.who.int/icd11referenceguide/en-2025-01/refguide.pdf)
- Local synthetic probes of the configured image at
  `http://127.0.0.1:8382/swagger/v2/swagger.json`, DORIS, CoDEdit and
  AutoCoding endpoints on 2026-09-26. No real death or VA data were used.
- `docker-compose.yml`, `app/services/who_icd_api.py`,
  `app/templates/help/pages/icd-codes-search-demo.html`,
  `app/templates/va_formcategory_partials/_va_cod_assessment_panel.html`,
  `app/models/va_final_assessments.py`,
  `app/models/va_reviewer_final_assessments.py`, and
  `app/utils/va_mapping/va_mapping_02_fieldcoder.py` in this repository.
