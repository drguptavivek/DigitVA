---
title: WHO ICD-11 Mortality Tabulation List, 2025-01 (frozen 2026-09-16)
doc_type: reference
status: active
owner: engineering
last_updated: 2026-09-16
---

# WHO ICD-11 Mortality Tabulation List, 2025-01 (frozen 2026-09-16)

## Role

Frozen upstream copy of WHO's list for international statistical tabulation of
mortality in ICD-11, compiled by WHO from its reporting requirements (including
the Sustainable Development Goals) and WHO-FIC expert input, and generated
programmatically from the ICD-11 release. It is a candidate built-in COD
reporting scheme for ICD-11-coded deaths, alongside the existing SRS India,
CMEA10 and WHO 2022 VA schemes, and a reference for grouping ICD-11 codes in
reports. No migration, service or command reads it yet. Plan:
`docs/planning/icd11-self-hosted-api-and-ect-plan.md`.

## Provenance

- Publisher: World Health Organization (WHO), ICD-11 browser download area,
  bundle `MortalityTabulationList_en.zip`, obtained by the project lead and
  extracted unchanged into this folder on 2026-09-16 (branch `icd-11`).
- The files inside the bundle are dated 2025-01-31 and the entity URIs use the
  release-independent form `http://id.who.int/icd/release/11/mms/...`. The
  expanded code lists were checked against the frozen 2025-01 Simple
  Tabulation (see below), so the list is treated as belonging to the 2025-01
  release.

| File | Bytes | MD5 | Notes |
|---|---:|---|---|
| `MortalityTabulationList.xlsx` | 62304 | `63b1962f39d23bd2a865dde46a6556b4` | one sheet `MortalityTabulationList`, 158 value sets |
| `MortalityTabulationList-Readme.pdf` | 97144 | `f703271844c02be00df94b60831a6439` | WHO's one-page explanation of the columns |

## Structure

One sheet with 11 columns, as described in WHO's readme PDF:

| Column | Meaning |
|---|---|
| `Value Set Name` | list number `M1` to `M158` |
| `Explanation` | the tabulated cause label |
| `Included Entities` | included entities, ranges or blocks with their codes, `\|`-separated |
| `Included Entities (URI)` | URIs of the included entities, comma-separated |
| `Excluded Entities` | entities removed from the included ranges |
| `Excluded Entities (URI)` | their URIs |
| `Included Value Sets` | other lists included (unused in this release) |
| `Excluded Value Sets` | other lists excluded (unused in this release) |
| `Tags` | cross-reference tags such as `WT-1-02`, or `New` |
| `Expanded codes` | every terminal ICD-11 code covered, comma-separated, for programmatic use |

Counts computed from the workbook on 2026-09-16:

| Measure | Value |
|---|---:|
| Value sets | 158 (M1 to M158) |
| Sets with exclusions | 20 |
| Sets using included or excluded value sets | 0 |
| Tag kinds | WT-: 90, New: 36, blank: 28, New?: 2, new: 1, New? or Down syndrom tag?: 1 |
| Distinct expanded codes across all sets | 12157 |
| Expanded codes resolving in the frozen 2025-01 code list | 12157 |
| Codes appearing in more than one set | 0 |
| Leaf MMS codes in chapters 01 to 25 covered by some set | 12157 of 14772 |
| Expanded codes per set | min 1, median 13, max 1077 |

Facts that matter for an importer:

- `Expanded codes` is the column to load; WHO has already resolved ranges and
  exclusions into terminal codes. Included and excluded entity columns explain
  how each set was built and can be shown as provenance.
- The `WT-` tags appear to reference the ICD-10 mortality tabulation list
  numbering; WHO's readme does not define them. Treat them as informational.
- The sets are meant to partition mortality coding; the overlap count above
  reports how many codes fall into more than one set in this release, which an
  importer must surface rather than resolve silently.
- Included-entity URI hosts: http://id.who.int/icd/release/11.

## Licence

ICD-11 content, including this list, is licensed under CC BY-ND 3.0 IGO per the
ICD-11 Terms of Use and License Agreement at
`https://icd.who.int/en/docs/icd11-license.pdf`. Reproductions must keep the
ICD-11 codes and URIs and carry WHO attribution. Nothing in this folder is
modified from the WHO download.
