---
title: WHO DORIS Web Behavior and API Shape Observed for DigitVA
doc_type: kb
status: active
owner: engineering
last_updated: 2026-09-26
---

# WHO DORIS Web Behavior and API Shape Observed for DigitVA

## Scope and evidence

This records a **synthetic, read-only browser trace** of a fresh WHO DORIS
workspace on 2026-09-26, WHO's published certificate exchange format, and
checks against DigitVA's pinned local `whoicd/icd-api:2.6.0` with ICD-11 MMS
`2026-01`. The owner's already open WHO certificate was not touched. WHO's
browser requests are observations of its current implementation, not a
supported API for DigitVA to call. The product plan is a DigitVA-owned form
using the **documented local ICD API** for terminology, DORIS and CoDEdit.
No WHO JavaScript bundle or sample source has been copied into DigitVA.

## Form and interaction shape

| Area | Visible controls and observed interaction | Certificate structure |
| --- | --- | --- |
| Administrative | Sex; birth/death dates; estimated age and unit | `AdministrativeData` |
| Frame A, Part I | Four visible lines A–D, separated by “Due to”; each line accepts multiple removable coded chips; interval and unit beside each line | Ordered `Part1[]`; each line has `Conditions[]`; each condition has its own `Interval` in JSON |
| Frame A, Part II | Multiple significant contributing conditions, with interval and unit | `Part2.Conditions[]` |
| Surgery | Surgery within four weeks; date and reason | `Surgery` |
| Autopsy | Requested; findings used | `Autopsy` |
| Manner/external cause | Manner; date of injury; description; place | `MannerOfDeath` |
| Fetal/infant | Multiple pregnancy, stillborn, survival hours, birth weight, pregnancy weeks, mother's age, perinatal maternal-condition text | `FetalOrInfantDeath` |
| Maternal | Pregnant; time from pregnancy; pregnancy contributed | `MaternalDeath` |
| Actions | Process CoDEdit, Process DORIS, new certificate, clear, examples, save to file | WHO web manages several MCCDs in one browser session; DigitVA Help needs one current editor with load/clear/process |

WHO's [web guide](https://icd.who.int/docs/doris/en/doris-web/) describes
term or code search in Frame A, the output summary, and textual, tabular,
rule-flow and rule-sequence views. The observed form also displayed a
completion summary. The Help implementation should reproduce the usable
interaction, not the WHO page's layout or browser-session storage.

### Conditional behavior actually observed

| Input change | WHO web result in this probe | DigitVA implication |
| --- | --- | --- |
| Sex → male | Pregnancy section marked inapplicable; pregnancy question disabled; follow-ups absent | Hide/disable these questions and omit their values from the processed certificate |
| Sex → female | Pregnancy question enabled | Offer yes/no/unknown |
| Pregnant → yes | Time-from-pregnancy and contribution choices enabled; time choice opened | Show those follow-ups; do not prefill an answer |
| Surgery → no | Date and reason remained visible and settable in this WHO build | Do not claim WHO hides every “if yes” field; DigitVA may hide inapplicable follow-ups, but must omit them from processing |
| Manner → disease | External-cause fields remained visible in the short probe | Test relevance before implementing conditional display |

The fetal/infant section also remained visible during an adult synthetic
case. Conditional display in DigitVA should follow clinical applicability
and the WHO certificate field meanings, with focused UI tests. A hidden
answer must not silently become an invented `9`/unknown value. If changing
an earlier answer would discard entered follow-up content, the editor must
make that effect clear and exclude inapplicable values from the processed
payload.

## ICD-11 search observed while typing

All URLs in this section were observed on WHO's **developer-test** search
service. DigitVA uses its pinned local WHO image via a same-origin server
boundary. WHO search response labels contain highlighted HTML; treat them
as untrusted when rendering.

| Input in a condition row | WHO web request | Response and UI |
| --- | --- | --- |
| Term `diabetes` | `POST /icd/release/11/2026-01/mms/search`, multipart form body with `q=diabetes%` | `destinationEntities` list; code, highlighted title, matching synonyms, details and postcoordination indicators; selecting `5A11` inserted a removable chip in line A |
| Term `tuberculosis` | Same `search` route with `q=tuberculosis%` | Results included simple `1B10.Z` and complete expressions such as `1B12.2 &XA0G74` |
| Code prefix `BA41` | `GET /icd/release/11/2026-01/mms/codeinfo/BA41?flexiblemode=true`, followed by `GET` of the MMS entity URI | `codeinfo` had `@id`, `code`, `stemId`; entity response gave title; UI offered `BA41` Acute myocardial infarction |
| Exact code `1B10.Z` | `codeinfo` lookup | UI offered the matching respiratory-TB category and inserted a chip on selection |

The observed term-search form also sent `chapterFilter` covering ICD-11
chapters, empty `subtreesFilter`, `includePostcoordination=true`,
`useBroaderSynonyms=false`, `useFlexiSearch=false`,
`includeKeywordResult=true`, `flatResults=true`,
`highlightingEnabled=true`, and `medicalCodingMode=true`. A 50-item
`diabetes` response had `resultChopped=true`; top-level keys included
`destinationEntities`, `error`, `errorMessage`, `resultChopped`,
`wordSuggestionsChopped`, `guessType`, `uniqueSearchId`, and `words`. A
result carried `id`, `stemId`, `theCode`, `title`, `matchingPVs`, score,
chapter, leaf/residual flags and postcoordination availability. Search
flags and response HTML are implementation details to recheck against the
pinned image, not constants to copy unexamined.

Selecting a term sent an additional WHO analytics event containing the
selected code/URI/search ID. DigitVA's existing authenticated ECT proxy
discards that event; the local ICD image has analytics disabled. The planned
public Help proxy should do the same. Start with the already integrated WHO
ECT for browser condition selection, because it supports complete code
expressions and existing server-side code/URI validation. Match the useful
WHO web behavior by showing each selected condition as a removable chip in
its line. A future mobile client needs a normalized DigitVA search API; it
cannot mount ECT's browser DOM.

## Expression versus condition versus causal line

The observed WHO search returned `1B12.2 &XA0G74` (“Tuberculous otitis
media”). On selection, it became **one chip** with complete code
`1B12.2&XA0G74`. Its one condition object carried two URI components joined
by ` & `. Adding `1B10.Z` beside it on Part I line B produced **two**
condition objects on the same line:

```json
{
  "Conditions": [
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
  ]
}
```

The `2026-01` URIs above were independently checked with the local
`codeinfo` endpoint; WHO's live web wrapper used corresponding release-less
URIs. The sixth fixture in `resource/doris_help_examples.json` tests the
release-pinned two-condition structure against local DORIS and CoDEdit.
DORIS returned `code=1B10.Z`, `reject=false`; CoDEdit returned no issue IDs.
This is a structure test, **not** a clinical claim about a causal relationship.
Likewise a `/` multi-stem expression or an `&` extension within one `Code`
is still one selected condition. A lower Part I line expresses “due to”; the
separators inside ICD-11 expressions do not.

## Certificate JSON shape to build in DigitVA

The [WHO certificate format](https://icd.who.int/docs/doris/en/json-format/)
defines these fields. Use one certificate object for the local DORIS/CoDEdit
POST, whereas WHO's exchange **file** format is an array of certificates.
Omit unknown optional objects/fields where appropriate; do not fill dummy
answers to satisfy a UI.

| JSON path | Values / meaning |
| --- | --- |
| `CertificateKey`, `Issuer`, `ICDVersion`, `ICDMinorVersion` | Optional identity/version metadata; the observed web wrapper also included `Comments` and `FreeText`; DigitVA should not transmit a VA identifier through public Help |
| `AdministrativeData.DateBirth`, `.DateDeath`, `.Sex`, `.EstimatedAge` | Dates or ISO 8601 duration; sex `1` male, `2` female, `9` unknown |
| `Part1[].Conditions[]`, `Part2.Conditions[]` | Ordered lines; condition object `Text`, `Code`, `LinearizationURI`, optional `FoundationURI`, `Interval` |
| `Surgery.WasPerformed`, `.Date`, `.Reason` | `0` no, `1` yes, `9` unknown; date/reason only when known/applicable |
| `Autopsy.WasRequested`, `.Findings` | `0` no, `1` yes, `9` unknown |
| `MannerOfDeath.MannerOfDeath`, `.DateOfExternalCauseOrPoisoning`, `.DescriptionExternalCause`, `.PlaceOfOccuranceExternalCause` | Manner enum `0` disease, `1` accident, `2` self harm, `3` assault, `4` legal intervention, `5` war, `6` undetermined, `7` pending, `9` unknown; place enum `0`–`9` per WHO format |
| `FetalOrInfantDeath.MultiplePregnancy`, `.Stillborn`, `.DeathWithin24h`, `.BirthWeight`, `.PregnancyWeeks`, `.AgeMother`, `.PerinatalDescription` | Fetal/perinatal context; unknown answers when offered use `9` |
| `MaternalDeath.WasPregnant`, `.TimeFromPregnancy`, `.PregnancyContribute` | Pregnancy yes/no/unknown `1`/`0`/`9`; timing `0` at death, `1` within 42 days, `2` 43 days–1 year, `3` ≥1 year, `9` unknown |

WHO documents unknown onset-to-death intervals as `""`, `"P"`, or `"PT"`.
Its web wrapper request contained `FetalOrInfantDeath.BirthHeight` while the
format page names `BirthWeight`; the local image accepted our `BirthWeight`
fixture, but acceptance does not prove that the engine used it. This field
requires a specific versioned test before clinical use. Keep WHO's spelled
key `PlaceOfOccuranceExternalCause` at the exchange boundary even though
“Occurance” is misspelled in ordinary English.

## WHO web processing wrapper versus local ICD API

| Operation | WHO web request observed | DigitVA target |
| --- | --- | --- |
| CoDEdit | `POST https://icd.who.int/doris/api/ucod/codedit/` with `{DeathCertificate: {...}, DorisSettings: {lang: "en"}}` | `POST /icd/release/11/2026-01/codedit` on local image with one certificate object |
| DORIS | `POST https://icd.who.int/doris/api/ucod/underlyingcauseofdeath/` with `{DeathCertificate: {...}, DorisSettings: {fullyAutomatic: true, lang: "en"}}` | `POST /icd/release/11/2026-01/doris` on local image with one certificate object |

The web wrapper request expanded absent form values to `null` or empty
strings, sent five `Part1` line objects (including empty lines), and included
web/session output fields (`UCComputed`, `StructuredReport`, report and
CoDEdit placeholders). The wrapper response returned the enriched
certificate. The observed CoDEdit response added `CE-Checks`,
`CE-ImportantChecks`, `CE-HighPriorityChecks`, `CE-IssueIds`, and
`CE-TabularReport`. The observed DORIS response added `UCComputed.UC`
(single selected stem), `UCComputed.UCComplete` (complete expression),
`UCComputed.Report`, `UCComputed.Warnings`, `ReportTabular`,
`ReportRuleFlow`, `ReportRuleProgression`, and `DRS-IssueIds`. Its output
modal displayed the single UCOD and complete UCOD separately, then warnings,
short/full explanations and report-view tabs. This wrapper is not required
for DigitVA and should not become a dependency.

The [documented ICD API DORIS response](https://icd.who.int/docs/icd-api/DORISSupport/)
instead has `code`, `stemCode`, `uri`, `stemURI`, `report`,
`tabularReport`, `reject`, `error`, and `warning`. The documented CoDEdit
response has `report`, `tabularReport`, and `issueIds`. The server should
return both complete direct responses with independent processor status and
the release/digest used. A WHO HTTP 200 with `reject=true` is not a computed
UCOD. Render table, rule-flow and sequence views from `tabularReport` as
secondary views; keep the raw/readable report when a visualization fails.
WHO's [vanilla-JS visualization sample](https://github.com/ICD-API/ICD-API-DORIS-Samples)
demonstrates these views but is not a certificate component and has no
declared repository license.

## DigitVA acceptance implications

1. Public Help: load/edit six synthetic examples or start blank; search by
   term and code; support multiple conditions per line and complete
   expressions; process the current certificate with both engines; display
   independent outputs without persistence.
2. Clinical unmasked ICD-11 DORIS mode: reuse the certificate schema and
   result views, add active allocation and project checks, then save the
   server-verified certificate and engine results separately from the MO's
   final underlying COD.
3. Verify UI relevance/visibility by field, complete code and URI
   provenance, stale-result handling, malformed/rejected responses,
   maternal and perinatal warnings, and the mixed TB fixture. Never infer
   clinical causal links from a code cluster or the rule diagram.
