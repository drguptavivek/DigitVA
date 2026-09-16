---
title: ICD-11 MMS 2025-01 Simple Tabulation (frozen 2026-09-16)
doc_type: reference
status: active
owner: engineering
last_updated: 2026-09-16
---

# ICD-11 MMS 2025-01 Simple Tabulation (frozen 2026-09-16)

## Role

Frozen upstream snapshot of the WHO ICD-11 MMS linearization (English) for the
planned `mas_icd11_mms` catalog. This is the intended seed source for the
ICD-11 catalog migration. No migration, service or command reads it yet.

Plan: `docs/planning/icd11-self-hosted-api-and-ect-plan.md`. Companion ICD-11
reference data: `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md`.

## Provenance

- Publisher: World Health Organization (WHO), ICD-11 browser download area,
  "Simple Tabulation" export of the MMS linearization, English.
- Obtained by the project lead as `SimpleTabulation-ICD-11-MMS-en.zip` and
  extracted unchanged into this folder on 2026-09-16 (branch `icd-11`).
- The WHO version stamp in the last column header is `Version:2025 Jan 24 - 22:30 UTC`
and the browser links inside point at `https://icd.who.int/browse/latestrelease/mms/en`,
so this is the published ICD-11 release current in January 2025, the 2025-01 release.
- The WHO ICD API container defaults to the 2026-01 release. The catalog release and the
container's `include` value must match, so either pin the container to `2025-01_en` or
download the 2026-01 Simple Tabulation and freeze it in a sibling folder before seeding.

| File | Bytes | MD5 | Notes |
|---|---:|---|---|
| `SimpleTabulation-ICD-11-MMS-en.txt` | 9982975 | `9ef65ca6708e9fc766a34ca28d3a9b80` | tab-separated UTF-8 with BOM, CRLF line endings; the import source |
| `SimpleTabulation-ICD-11-MMS-en.xlsx` | 3650171 | `954302df168f93fcd45c2d00267e71b0` | same content as a spreadsheet; the xlsx sheet has the same number of data rows as the text file |
| `who-readme.txt` | 1228 | `0b87411138990a52f258c9feea516306` | WHO's own column notes, renamed from `readme.txt` inside the bundle |

`.gitattributes` marks the text file as `-text` so Git never converts its line
endings; the checked-in bytes match the WHO download.

## Structure

18 tab-separated columns. The first line is the header; the last header
cell carries WHO's version stamp (`Version:2025 Jan 24 - 22:30 UTC`).

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
| `Version:2025 Jan 24 - 22:30 UTC` | WHO version stamp carried in the header; the column itself is empty |

Counts computed from the text file on 2026-09-16:

| Measure | Value |
|---|---:|
| Data rows | 36782 |
| Chapters | 28 (01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, V, X) |
| Blocks (no code) | 1415 |
| Categories | 35339 |
| Coded categories | 35339 |
| Distinct codes | 35339 |
| Placeholder `_NOCODEASSIGNED` rows | 0 |
| Residual categories | 5355 |
| Leaf rows | 30981 |
| Dotted codes | 12892 |
| Code length distribution | 4 chars: 5861, 5 chars: 3456, 6 chars: 21823, 7 chars: 4199 |

Facts that matter for an importer:

- Every row has a distinct `Linearization URI`: confirmed. It is the
  stable key for a catalog row within a release.
- Residual categories have an empty `Foundation URI` (5355 of 5355 residual rows;
  0 non-residual rows lack one). A catalog column for the foundation URI
  must be nullable.
- Codes are stem codes only: 0 codes contain `&` or `/`. Extension codes
  (chapter X) appear as ordinary categories.
- The file has no parent column. `Title` carries one `- ` prefix per level of
  absolute depth (chapters have none), and the rows are in linearization
  order, so the parent of a row is the nearest preceding row one level
  shallower. Check: depth never rises by more than one step between
  consecutive rows (0 violations); every chapter row has depth 0
  (confirmed). Importers must strip the prefixes from titles.
- `Primary tabulation` is blank for chapters and blocks and is set for every
  category (16560 True, 18779 False). It is False for every category in
  chapters 26, V, X and for a subset of categories elsewhere, for example
  1G40 and 1G41 (sepsis) and 1D00 to 1D03 (infectious encephalitis and
  meningitis "not elsewhere classified"). WHO does not define the flag in its
  readme. Treat it as informational until its meaning is confirmed against
  the ICD API entity properties, and do not derive coding policy from it.
- `BrowserLink` values are spreadsheet formulas (`=hyperlink(...)`), not plain
  URLs.

## Licence

ICD-11 content is licensed under Creative Commons Attribution-NoDerivatives
3.0 IGO (CC BY-ND 3.0 IGO), per the ICD-11 Terms of Use and License Agreement
at `https://icd.who.int/en/docs/icd11-license.pdf`. Reproductions must keep the
ICD-11 codes and URIs and carry WHO attribution. Nothing in this folder is
modified from the WHO download apart from the renamed readme.
