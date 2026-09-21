---
title: WHO ICD-10 to ICD-11 Mapping Tables, 2025-01 (frozen 2026-09-16)
doc_type: reference
status: active
owner: engineering
last_updated: 2026-09-21
---

# WHO ICD-10 to ICD-11 Mapping Tables, 2025-01 (frozen 2026-09-16)

## Role

Frozen upstream copy of WHO's official mapping tables between ICD-10 and the
ICD-11 MMS linearization, release 2025-01. They are reference inputs for the
ICD-11 work planned in `docs/planning/icd11-self-hosted-api-and-ect-plan.md`:

- trending and translating ICD-10-coded records into ICD-11 terms;
- cross-checking DigitVA's ICD-11 to VA bucket assignment against the existing
  ICD-10 bucket mappings, by mapping ICD-11 codes back to ICD-10 with the
  `11To10MapToOneCategory` table;
- reviewing which ICD-10 codes have no exact ICD-11 equivalent (the
  `Subclass` relations in the foundation table).

The native ICD-11 bucket generator
(`app/services/cod_bucket_icd11_generator.py`, `flask cod-buckets
generate-icd11`) reads `11To10MapToOneCategory.txt` for its cross-check;
nothing else reads these files yet.

## Provenance

- Publisher: World Health Organization (WHO), ICD-11 browser download area,
  "Mapping tables" bundle (`mapping.zip`), obtained by the project lead and
  extracted unchanged into this folder on 2026-09-16 (branch `icd-11`).
- Every table carries the WHO version stamp `2025-Jan-24` in its last header
  cell, and every linearization URI is under
  `http://id.who.int/icd/release/11/2025-01/mms/`, so the tables belong to the
  ICD-11 2025-01 release, the same release as the frozen Simple Tabulation in
  `icd11-mms-2025-01-base-2026-09-16/`.
- The text files are tab-separated UTF-8; `.gitattributes` keeps them
  byte-exact.

| File | Bytes | MD5 | Role |
|---|---:|---|---|
| `10To11MapToOneCategory.txt` | 3083729 | `baae34f03596f46d198169b7bf94c0ea` | one preferred ICD-11 MMS target per ICD-10 entity (chapters, blocks and codes); targets may be postcoordinated stem and extension code pairs joined by `&` |
| `10To11MapToOneCategory.xlsx` | 956853 | `450fea72f450fbe026aa057f26b6d165` | same table as a spreadsheet |
| `10To11MapToMultipleCategories.txt` | 3786509 | `ad78b700e43c7dc878bdd95d02e0de56` | all ICD-11 MMS targets per ICD-10 entity, one row per target |
| `10To11MapToMultipleCategories.xlsx` | 1157275 | `30cf644d791cc49a5f36b0ac1b75d23a` | same table as a spreadsheet |
| `11To10MapToOneCategory.txt` | 2917703 | `38e12635dc3602950740d6c2bb13eda8` | one ICD-10 target per ICD-11 MMS linearization entity in chapters 01 to 25; targets may be ICD-10 block ranges |
| `11To10MapToOneCategory.xlsx` | 967714 | `5277f9b13e98fd5324e3eb16978b7248` | same table as a spreadsheet |
| `foundation_10To11MapToOneCategory.txt` | 2097874 | `c5744b9e2e69ac715ab25b086e0aaaba` | one ICD-11 foundation entity per ICD-10 entity, with two unnamed trailing cells: a relation kind (`Equivalent` or `Subclass`) and a level distance (0 to -3) |
| `foundation_10To11MapToOneCategory.xlsx` | 666198 | `d9ed670d94d30a64f2568d889f451df8` | same table as a spreadsheet |
| `foundation_11To10MapToOneCategory.txt` | 6691444 | `45f13cfd02f6472e45491e0e5ed188f8` | one ICD-10 target per ICD-11 foundation entity, including foundation entities that carry no MMS code |
| `foundation_11To10MapToOneCategory.xlsx` | 2268680 | `da3e13a45eb11d841c9eeae8b1b71a16` | same table as a spreadsheet |
| `who-readme.txt` | 1829 | `accbf3b91229f1198703209bb7c51e97` | WHO's column notes, renamed from `readme.txt` inside the bundle |

## Structure

WHO's `who-readme.txt` names the column concepts (ICD-10 chapter, code, title,
class kind and depth; ICD-11 chapter, foundation URI, linearization URI, code,
title and class kind). The actual header cells differ slightly per file, and in
two files the data rows carry more cells than the header names:

- **`10To11MapToOneCategory.txt`**: 12597 rows; 13 header cells, 12 data cells per row (the last header cell is the WHO version stamp `2025-Jan-24`).
  ICD-10 side: chapter 22, block 274, category 11243, modifiedcategory 1058; 12597 distinct ICD-10 entities, of which 12301 are editable codes in our ICD-10 2019 catalog (12475 editable codes in total).
  ICD-11 side: 6693 distinct target strings; 784 rows postcoordinated with `&`; 58 rows offer alternatives joined by `/`; stems not found in the frozen 2025-01 code list: 0.
  Rows with a blank ICD-11 code (blocks): 98.
- **`10To11MapToMultipleCategories.txt`**: 15630 rows; 13 header cells, 12 data cells per row (the last header cell is the WHO version stamp `2025-Jan-24`).
  ICD-10 side: chapter 79, block 514, category 13861, modifiedcategory 1176; 12597 distinct ICD-10 entities, of which 12301 are editable codes in our ICD-10 2019 catalog (12475 editable codes in total).
  ICD-11 side: 8740 distinct target strings; 860 rows postcoordinated with `&`; 116 rows offer alternatives joined by `/`; stems not found in the frozen 2025-01 code list: 0.
  Rows with a blank ICD-11 code (blocks): 59.
  1285 ICD-10 entities have more than one target; the maximum is 42 targets.
- **`11To10MapToOneCategory.txt`**: 17919 rows; 8 header cells, 7 data cells per row (the last header cell is the WHO version stamp `2025-Jan-24`).
  6399 distinct ICD-10 targets, 6183 of them editable codes in our ICD-10 2019 catalog; the rest are block ranges or chapters.
  ICD-11 side: 17256 distinct target strings; 0 rows postcoordinated with `&`; 0 rows offer alternatives joined by `/`; stems not found in the frozen 2025-01 code list: 25 (the chapter rows, whose code cell holds the chapter number).
  Rows with a blank ICD-11 code (blocks): 663.
  Covers 17231 of the 17231 MMS codes in chapters 01 to 25; chapters 26, V and X are not mapped. 195 distinct targets are ICD-10 block ranges such as `A15-A19`.
- **`foundation_10To11MapToOneCategory.txt`**: 12597 rows; 8 header cells, 9 data cells per row (the last header cell is the WHO version stamp `2025-Jan-24`).
  ICD-10 side: Chapter 22, Block 274, Category 12301; 12597 distinct ICD-10 entities, of which 12301 are editable codes in our ICD-10 2019 catalog (12475 editable codes in total).
  This table has no ICD-11 code column; targets are foundation URIs and titles only.
  Trailing cells: Equivalent at distance 0: 7858; Subclass at distance 0: 2472; Subclass at distance -1: 1908; Subclass at distance -2: 313; Subclass at distance -3: 42; blank at distance -1: 4.
- **`foundation_11To10MapToOneCategory.txt`**: 48595 rows; 7 header cells, 6 data cells per row (the last header cell is the WHO version stamp `2025-Jan-24`).
  8536 distinct ICD-10 targets, 8315 of them editable codes in our ICD-10 2019 catalog; the rest are block ranges or chapters.
  ICD-11 side: 12185 distinct target strings; 0 rows postcoordinated with `&`; 0 rows offer alternatives joined by `/`; stems not found in the frozen 2025-01 code list: 25 (the chapter rows, whose code cell holds the chapter number).
  Rows with a blank ICD-11 code (foundation entities that carry no MMS code): 36410.

Facts that matter for anyone using the tables:

- `10To11` targets are written as codes, and a postcoordinated target such as
  `1A00&XN8P1` means stem code `1A00` with extension code `XN8P1`. Stem codes
  resolve against the frozen 2025-01 Simple Tabulation; extension codes are
  chapter X entries in the same file. A few targets list alternatives joined
  by `/` and must be handled explicitly.
- ICD-10 entities in these tables include modifier-derived codes (class kind
  `modifiedcategory`), but fewer of them than our ICD-10 catalog expands from
  the ClaML modifiers, which is why 174 of our editable codes have
  no row.
- `11To10MapToOneCategory` is keyed by linearization URI and includes block
  rows with an empty ICD-11 code. Its ICD-10 targets can be block ranges,
  which do not exist as rows in `mas_icd10_2019_2` and need range handling.
- The foundation tables map at the foundation layer, where many entities have
  no MMS code; use the linearization tables for code-level work.

## Licence

WHO publishes these tables in the ICD-11 download area and their use is
governed by the ICD-11 Terms of Use and License Agreement at
`https://icd.who.int/en/docs/icd11-license.pdf`. That agreement states that
mappings between other classifications and ICD-11 fall outside the CC BY-ND
licence for ICD-11 content. These are WHO's own tables, reproduced unchanged for
internal project use; confirm the terms with WHO before redistributing them or
publishing anything derived from them outside the project.
