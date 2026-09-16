---
title: ICD-11 MMS 2026-01 Simple Tabulation (frozen 2026-09-16)
doc_type: reference
status: active
owner: engineering
last_updated: 2026-09-16
---

# ICD-11 MMS 2026-01 Simple Tabulation (frozen 2026-09-16)

## Role

Frozen upstream snapshot of the WHO ICD-11 MMS linearization (English) for the
planned `mas_icd11_mms` catalog. This is the release to seed from: it matches
the default release of the WHO ICD API container (`include=2026-01_en`). No
migration, service or command reads it yet. Plan:
`docs/planning/icd11-self-hosted-api-and-ect-plan.md`.

The 2025-01 export in `../icd11-mms-2025-01-base-2026-09-16/` stays checked in
because WHO's ICD-10 mapping tables and mortality tabulation list in this
repository belong to that release; WHO's change list between the two releases
is in `../icd11-mms-changes-2026-01-vs-2025-01-2026-09-16/`.

## Provenance

- Publisher: World Health Organization (WHO), ICD-11 browser download area,
  "Simple Tabulation" export of the MMS linearization, English.
- Obtained by the project lead as `SimpleTabulation-ICD-11-MMS-en.zip` and
  extracted unchanged into this folder on 2026-09-16 (branch `icd-11`).
- The WHO version stamp in the last named header cell is `Version:2026 Jan 17 - 05:30 UTC`, the
  files inside the bundle are dated 2026-01-27, and the browser links point at
  `https://icd.who.int/browse/...`, the release browser. This is the ICD-11
  2026-01 release.

| File | Bytes | MD5 | Notes |
|---|---:|---|---|
| `SimpleTabulation-ICD-11-MMS-en.txt` | 11661691 | `47162fc8df5c7813e9c2aafddf846b5f` | tab-separated UTF-8 with BOM, CRLF row terminators, quoted title cells; the import source |
| `SimpleTabulation-ICD-11-MMS-en.xlsx` | 4005948 | `bb4d05c1f0b10452cf2d8926c84dc56a` | same content as a spreadsheet, plus 66 spurious rows (see below) |
| `who-readme.txt` | 1228 | `0b87411138990a52f258c9feea516306` | WHO's column notes, renamed from `readme.txt`; unchanged since the 2025-01 bundle and silent on the two new columns |

`.gitattributes` marks the text file as `-text` so Git never converts its line
endings; the checked-in bytes match the WHO download.

## Structure

20 header cells (the last is empty); 37052 data rows of 19 cells.
Two columns are new compared with the 2025-01 export: `CodingNote` and
`Parent`.

| Column | Meaning |
|---|---|
| `Foundation URI` | unique identifier for the entity that will not change |
| `Linearization URI` | unique identifier for this version of the classification; includes the linearization name (mms) |
| `Code` | ICD-11 code for the entity; groupings do not have a code |
| `BlockId` | identifier for high level groupings that do not bear a code |
| `Title` | title of the entity |
| `ClassKind` | one of chapter, block, category |
| `DepthInKind` | depth within the class kind, for example a category with 2 has a category parent and a non-category grandparent |
| `IsResidual` | true if the entity is a residual category (other specified or unspecified) |
| `ChapterNo` | the chapter that the entity is in |
| `BrowserLink` | direct link to this entity in the ICD-11 browser, stored as a spreadsheet hyperlink formula |
| `isLeaf` | true if this entity does not have any children |
| `Primary tabulation` | left undefined in WHO's readme; see the empirical notes below |
| `Grouping1` | groupings that the entity is included in (block ids, first level) |
| `Grouping2` | groupings that the entity is included in (second level) |
| `Grouping3` | groupings that the entity is included in (third level) |
| `Grouping4` | groupings that the entity is included in (fourth level) |
| `Grouping5` | groupings that the entity is included in (fifth level) |
| `CodingNote` | new in this release and not described in WHO's readme: the coding note shown in the browser, which may contain line breaks |
| `Parent` | new in this release and not described in WHO's readme: the Foundation URI of the parent entity; empty for chapters |
| `Version:2026 Jan 17 - 05:30 UTC` | WHO version stamp carried in the header; the column itself is empty |

Counts computed from the text file on 2026-09-16:

| Measure | Value |
|---|---:|
| Data rows | 37052 |
| Chapters | 28 (01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, V, X) |
| Blocks (no code) | 1360 |
| Categories | 35664 |
| Coded categories (all distinct) | 35664 |
| Residual categories | 5374 |
| Leaf rows | 31194 |
| Rows with a coding note | 635 (of which 50 contain line breaks) |
| Dotted codes | 12927 |
| Code length distribution | 4 chars: 5914, 5 chars: 3627, 6 chars: 21902, 7 chars: 4221 |

Facts that matter for an importer:

- **Parse the text file on CRLF row boundaries, not on every line feed.**
  50 coding notes contain bare line feeds inside an unquoted cell. Splitting
  on any newline yields fragment rows; splitting on `\r\n` yields exactly
  37052 rows of 19 cells. Title cells are quoted in the file, so parse each
  row with a CSV reader (tab delimiter) rather than a plain split.
- **The xlsx is not a clean alternative.** WHO's export writer carried the same
  line breaks into the spreadsheet as 66 extra rows that hold only the
  remainder of a note and the parent URI, with every other cell blank. Rows
  with an empty `ClassKind` must be dropped, after which the xlsx matches the
  text file row for row.
- **`Parent` gives the parent's Foundation URI** and is empty only for the
  28 chapters. It agrees with the parent derived from row order and title
  depth for all 37024 rows that carry it, so either method works; prefer the
  column and keep the derivation as a consistency check.
- Every row has a distinct `Linearization URI`, the stable key within a
  release. Residual categories have an empty `Foundation URI` (5374 of
  5374 residual rows; 0 non-residual rows lack one).
- Codes are stem codes only (0 codes contain `&` or `/`). Extension codes
  (chapter X) appear as ordinary categories.
- `Title` still carries one `- ` prefix per level of absolute depth; depth never
  rises by more than one step between consecutive rows (0 violations).
  Importers must strip the prefixes.
- `Primary tabulation` is blank for chapters and blocks and set for every
  category (16584 True, 19080 False), False for every category in
  chapters 26, V, X. WHO does not define it; treat it as informational.
- `BrowserLink` values are spreadsheet formulas, not plain URLs.

## Differences From the 2025-01 Export

Comparing coded categories with `../icd11-mms-2025-01-base-2026-09-16/`:

| Change | Count |
|---|---:|
| Codes added | 354 (of which 308 chapter X extension codes and 34 residual `Y`/`Z` codes elsewhere) |
| Codes removed | 29 (of which 7 chapter X) |
| Codes kept with a changed title | 209 |

WHO's own change lists in `../icd11-mms-changes-2026-01-vs-2025-01-2026-09-16/`
account for these: every code in WHO's main-chapter added and removed lists
appears in the sets above, and the remainder are chapter X changes, residual
codes generated under new parents, and the moved codes WHO lists separately.

## Licence

ICD-11 content is licensed under Creative Commons Attribution-NoDerivatives
3.0 IGO (CC BY-ND 3.0 IGO), per the ICD-11 Terms of Use and License Agreement
at `https://icd.who.int/en/docs/icd11-license.pdf`. Reproductions must keep the
ICD-11 codes and URIs and carry WHO attribution. Nothing in this folder is
modified from the WHO download apart from the renamed readme.
