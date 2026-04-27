---
title: ICD-10 Reference Catalog Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-27
---

# ICD-10 Reference Catalog Policy

## Purpose

Define how DigitVA stores and refreshes its ICD-10 2019 hierarchy reference
catalog.

## Policy

1. DigitVA stores the ICD-10 2019 hierarchy as master reference data in
   `mas_icd10_2019_2`.
2. The authoritative structure source for this catalog is the checked-in WHO
   ICD-10 2019 ClaML XML snapshot and the generated hierarchy CSV derived from
   it.
3. Fresh schema creation for `mas_icd10_2019_2` must seed the table from the
   checked-in generated hierarchy CSV during migration.
4. The reference catalog stores only hierarchy and local policy fields needed
   for app behavior; DigitVA does not mirror all WHO descriptive metadata.
5. Import must be idempotent.
6. Re-running the import must:
   - update structural hierarchy fields for codes still present in the source
   - insert newly introduced codes
   - mark missing codes inactive instead of deleting them
7. Import must not require a database reset or table truncate.
8. Existing local policy curation must be preserved by default on rerun.
9. Policy fields may be refreshed from source only through an explicit operator
   action.
10. ICD coding-time lookup must read from `mas_icd10_2019_2`, not the legacy
    `va_icd_codes` table.
11. Coding-time lookup must return only selectable `three_character` and
    `detailed_code` rows.
12. Coding-time lookup must apply submission-specific policy filters using:
    - `va_deceased_age_normalized_days` to derive `neonate`, `infant`,
      `child`, or `adult`
    - `va_deceased_gender` to enforce `male` / `female` restrictions
13. Coding-time detailed child lookup must return only selectable detailed
    descendants for the chosen three-character code.
14. The generic authenticated ICD search endpoint at `/api/v1/icd10/search`
    must read from `mas_icd10_2019_2`, restricted to active
    `three_character` and `detailed_code` rows.
15. The legacy `va_icd_codes` catalog is deprecated as of 2026-04-20 and must
    not be used for new runtime ICD lookup features.

## Stored Hierarchy Scope

DigitVA stores enough ICD data to reconstruct the coding hierarchy:

- chapters
- blocks
- three-character categories
- detailed dotted codes

The stored row includes denormalized ancestry fields such as:

- `parent_code`
- `chapter_code`
- `block_code`
- `three_character_code`

The generated hierarchy CSV must include modifier-derived detailed codes from
the ClaML XML, built from `<ModifiedBy>` and `<ModifierClass>` definitions. For
example, transport and diabetes modifier rows such as `V01.1`, `V10.4`, and
`E10.0` are stored as detailed-code rows even when they are not literal
`<Class>` elements in the XML.

## Local Policy Scope

DigitVA may curate coding behavior in the same table using fields such as:

- `is_coding_selectable`
- `sex_selectable`
- `age_group_selectable`
- `policy_status`
- `restriction_note`

These policy values are DigitVA-local rules and must not be inferred purely
from WHO hierarchy structure.

Current defaulting rule:

- new `three_character` rows default to:
  - `is_coding_selectable = true`
  - `sex_selectable = both`
  - `age_group_selectable = all`
- exceptions:
  - `S00` through `S99` do not receive those defaults automatically
  - `T00` through `T99` do not receive those defaults automatically
  - `U00` through `U99` do not receive those defaults automatically
  - `Z00` through `Z99` do not receive those defaults automatically
