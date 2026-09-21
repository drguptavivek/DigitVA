---
title: Migration Artifacts Index
doc_type: reference
status: active
owner: engineering
last_updated: 2026-09-21
---

# Migration Artifacts Index

This folder contains the frozen master-data inputs used by the current ICD/COD
rebuild migration and by built-in COD bucket reset-default behavior.

Current migration file:

- `migrations/versions/d6e7f8a9b0c1_rebuild_icd10_and_cod_bucket_master_data.py`

Load sequence in `upgrade()`:

1. ICD base catalog from `icd10-2019-base-2026-04-27/icd10_2019_hierarchy.csv`
2. WHO reviewed coding policy from
   `who-2022-va-icd-cod-2026-04-27/who_2022_icd10_2019_2_policy_reviewed.json`
3. SRS COD buckets from
   `srs-india-cod-2026-04-27/icd-10-CODES_SRS_India.xlsx`
4. CMEA10 COD buckets from
   `cmea10-cod-2026-04-27/icd-10-CODES_CMEA10_mapped.xlsx`
5. WHO COD buckets from
   `who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_Bucket_Mapping_document_derived.xlsx`

## Active inputs

### `icd10-2019-base-2026-04-27/`

- `icd10_2019_hierarchy.csv`
  - role: canonical ICD-10 2019 hierarchy rows loaded into `mas_icd10_2019_2`
  - called from:
    - `migrations/versions/d6e7f8a9b0c1_rebuild_icd10_and_cod_bucket_master_data.py`

- `icd102019en.xml`
  - role: frozen upstream reference kept with the ICD hierarchy artifact set
  - called from:
    - kept as migration artifact reference; the rebuild migration reads the CSV

### `srs-india-cod-2026-04-27/`

- `icd-10-CODES_SRS_India.xlsx`
  - role: source of truth for built-in `SRS_INDIA` COD bucket hierarchy and ICD mappings
  - called from:
    - rebuild migration
    - built-in SRS reset-default in `app/services/cod_bucket_mapping_service.py`
    - CLI `flask cod-buckets import-srs-india`

### `cmea10-cod-2026-04-27/`

- `icd-10-CODES_CMEA10_mapped.xlsx`
  - role: source of truth for built-in `CMEA10` COD bucket hierarchy and ICD mappings
  - called from:
    - rebuild migration
    - built-in CMEA10 reset-default in `app/services/cod_bucket_mapping_service.py`
    - CLI `flask cod-buckets import-cmea10`

### `who-2022-va-icd-cod-2026-04-27/`

- `who_2022_icd10_2019_2_policy_reviewed.json`
  - role: reviewed WHO ICD coding/assignability policy layered over the ICD-10 base catalog
  - called from:
    - rebuild migration

- `WHO_2022_VA_Bucket_Mapping_document_derived.xlsx`
  - role: source of truth for built-in `WHO_2022_VA` COD bucket hierarchy and ICD mappings
  - called from:
    - rebuild migration
    - built-in WHO reset-default in `app/services/cod_bucket_mapping_service.py`
    - CLI `flask cod-buckets import-who-2022-va`

## Pending inputs (not yet used by any migration)

These folders hold frozen upstream snapshots for planned work. Nothing reads
them yet; see `docs/planning/icd11-self-hosted-api-and-ect-plan.md`.

### `icd11-mms-2026-01-base-2026-09-16/`

- `SimpleTabulation-ICD-11-MMS-en.txt` and `SimpleTabulation-ICD-11-MMS-en.xlsx`
  - role: frozen WHO ICD-11 MMS 2026-01 linearization export (English), the
    intended seed source for the planned `mas_icd11_mms` catalog; matches the
    ICD API container's default release
  - called from: nothing yet
  - details: folder `README.md` (note the CRLF parsing rule and the new
    `Parent` and `CodingNote` columns)

### `icd11-mms-changes-2026-01-vs-2025-01-2026-09-16/`

- `changes_MMS_2026-01_2025-01-main.xlsx` and `changes_MMS_2026-01_2025-01-extensions.xlsx`
  - role: WHO's list of MMS changes between the 2025-01 and 2026-01 releases,
    bridging the 2026-01 catalog and the 2025-01 mapping tables and mortality
    tabulation list
  - called from: `changes_MMS_2026-01_2025-01-main.xlsx` (its `MovedTo` rows) by
    `app/services/cod_bucket_icd11_generator.py` (`flask cod-buckets generate-icd11`)
  - details: folder `README.md`

### `icd11-mms-2025-01-base-2026-09-16/`

- `SimpleTabulation-ICD-11-MMS-en.txt` and `SimpleTabulation-ICD-11-MMS-en.xlsx`
  - role: frozen WHO ICD-11 MMS 2025-01 linearization export (English), kept
    because the mapping tables and mortality tabulation list below belong to
    this release; superseded as the catalog seed by the 2026-01 export
  - called from: nothing yet
  - details: folder `README.md`

### `icd11-mms-dev11-snapshot-2026-09-16/`

- `SimpleTabulation-ICD-11-MMS-en.txt` and `SimpleTabulation-ICD-11-MMS-en.xlsx`
  - role: preview snapshot of WHO's development linearization, for diffing
    against the 2025-01 release only; must not seed any catalog
  - called from: nothing yet
  - details: folder `README.md`

### `icd11-icd10-mapping-tables-2025-01-base-2026-09-16/`

- five WHO mapping tables between ICD-10 and ICD-11 MMS 2025-01, as text and
  xlsx (`10To11MapToOneCategory`, `10To11MapToMultipleCategories`,
  `11To10MapToOneCategory`, `foundation_10To11MapToOneCategory`,
  `foundation_11To10MapToOneCategory`)
  - role: WHO's official ICD-10 to ICD-11 correspondence, for trending
    ICD-10-coded records and for cross-checking ICD-11 VA bucket assignment
  - called from: `11To10MapToOneCategory.txt` by `app/services/cod_bucket_icd11_generator.py` (`flask cod-buckets generate-icd11`)
  - details: folder `README.md`

### `who-2022-va-icd11-native-2026-09-21/`

- `icd11_generated_mappings.csv`, `icd11_review.csv`,
  `icd11_unmapped_with_suggestion.csv`
  - role: generator report for the native ICD-11 table of `WHO_2022_VA_2026`
    (owner decisions 2026-09-21): what was mapped, what needs the owner's
    review, and what stays unmapped with the crosswalk's suggestion
  - called from: written by `app/services/cod_bucket_icd11_generator.py` (`flask cod-buckets generate-icd11`); read by nothing
  - details: folder `README.md`

### `icd11-mortality-tabulation-list-2025-01-base-2026-09-16/`

- `MortalityTabulationList.xlsx`
  - role: WHO's ICD-11 mortality tabulation list (158 value sets with expanded
    code lists), a candidate built-in COD reporting scheme for ICD-11
  - called from: nothing yet
  - details: folder `README.md`

## Archived supporting inputs

Some older review workbooks and helper artifacts were moved to
`docs/icd-causegrp-mappings/archive/` to reduce confusion. Those files may
explain how the retained artifacts were derived, but they are not part of the
current migration/reset execution path.
