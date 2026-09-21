---
title: WHO ICD-11 MMS Change List, 2026-01 versus 2025-01 (frozen 2026-09-16)
doc_type: reference
status: active
owner: engineering
last_updated: 2026-09-21
---

# WHO ICD-11 MMS Change List, 2026-01 versus 2025-01 (frozen 2026-09-16)

## Role

WHO's own list of what changed in the ICD-11 MMS linearization between the
2025-01 and 2026-01 releases. It is the bridge between the two frozen Simple
Tabulation exports in this folder's siblings, and between the 2026-01 catalog
release and the 2025-01 mapping tables and mortality tabulation list. The native ICD-11 bucket generator
(`app/services/cod_bucket_icd11_generator.py`) reads the main workbook's
`MovedTo` rows to translate 2026-01 codes back to 2025-01 before the
crosswalk lookup; nothing else reads it yet.

## Provenance

- Publisher: World Health Organization (WHO), ICD-11 browser download area,
  bundle `changes_MMS_2026-01_2025-01.zip`, obtained by the project lead and
  extracted unchanged into this folder on 2026-09-16 (branch `icd-11`).
- Files inside the bundle are dated 2026-01-27, the same day as the 2026-01
  Simple Tabulation export.

| File | Bytes | MD5 | Notes |
|---|---:|---|---|
| `changes_MMS_2026-01_2025-01-main.xlsx` | 10306 | `9c2b5ca038f5f7a9d4f4e856fded6d70` | 66 changes in chapters 01 to 26, with a header row |
| `changes_MMS_2026-01_2025-01-extensions.xlsx` | 20883 | `7010caca9b43f632f6f4f8fbd5fefe84` | 318 changes in chapter X (extension codes), without a header row |

## Structure

Both workbooks have one sheet with the same seven data columns: chapter,
foundation URI, release URI in 2025-01, release URI in 2026-01, code, title and
status. The main workbook has a header row and an eighth, empty column titled
"Comparison between versions 2025-01 and 2026-01"; the extensions workbook
has no header row and starts directly with data.

Status values, as counted on 2026-09-16:

- main chapters: `NewlyAdded` 39; `Removed` 18; `MovedAboveShoreline` 5; `MovedTo` 2; `MovedUnderShoreline` 2
- chapter X extensions: `NewlyAdded` 243; `Grouping became category` 58; `MovedAboveShoreline` 10; `Removed` 7

Reading the statuses: WHO calls the boundary between coded MMS categories and
foundation-only entities the "shoreline". `MovedAboveShoreline` means a
foundation entity gained a code in 2026-01, `MovedUnderShoreline` means it lost
its code, `MovedTo` gives the old and new code in the code cell (for example
`3B62.5 -> 4A20.20`), and `Grouping became category` marks chapter X groupings
that now carry codes. In the extensions workbook the code cell holds a release
URI rather than a code for some rows.

Reconciliation against the two frozen exports: all 39 `NewlyAdded` and all
18 `Removed` codes in the main workbook appear in the added and removed sets
computed from the tabulations (354 added, 29 removed). The rest of that
difference is chapter X, residual `Y`/`Z` codes generated under new parents,
and the moved codes listed above.

## Licence

ICD-11 content is licensed under CC BY-ND 3.0 IGO per the ICD-11 Terms of Use
and License Agreement at `https://icd.who.int/en/docs/icd11-license.pdf`.
Nothing in this folder is modified from the WHO download.
