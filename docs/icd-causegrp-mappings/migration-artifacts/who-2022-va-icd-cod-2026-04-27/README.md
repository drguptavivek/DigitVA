---
title: WHO 2022 VA ICD And COD Migration Artifacts
doc_type: migration-artifact
status: active
owner: engineering
last_updated: 2026-09-20
---

# WHO 2022 VA ICD And COD Migration Artifacts

This folder contains the fixed inputs for the 2026-04-27 WHO 2022 VA ICD
assignability and COD bucket migration.

Files:

- `who_2022_icd10_2019_2_policy_reviewed.json`
  - reviewed WHO 2022 ICD assignability policy
  - generated from the WHO 2022 crosswalk, then post-processed with the
    reviewed CMEA10 blank-code decision workbook
- `WHO_2022_VA_Bucket_Mapping_document_derived.xlsx`
  - document-derived WHO 2022 VA COD bucket mapping
  - generated from the reviewed WHO 2022 assignability policy so every policy
    row has a COD bucket mapping at import time
  - was derived using archived review workbooks for final transport and
    assignability decisions
- `WHO_2022_VA_Bucket_Mapping_admin_overrides.csv`
  - 34 ICD-to-bucket mappings added through the live admin bucket editor
    (`source_sheet=admin_cod_bucket_editor`) that the WHO derivation above
    never produced -- clinically plausible gaps such as heart failure (I50),
    the K70-K76 liver group, and unknown-cause codes
  - frozen 2026-09-20 (bead `digitva-2g7`) so a fresh import reaches the same
    2,414 mappings a long-lived deployment has, instead of the workbook's
    2,380
  - applied by `flask cod-buckets import-who-2022-va` after the workbook rows,
    via `_apply_who_2022_va_admin_overrides` in
    `app/services/cod_bucket_mapping_service.py`; a live admin edit made after
    this freeze wins over the frozen value on re-import

Archived supporting inputs:

- `docs/icd-causegrp-mappings/archive/migration-artifacts/who-2022-va-icd-cod-2026-04-27/WHO_2022_VA_RTA_NonRTA_Review.xlsx`
  - frozen review workbook for transport ICD code assignment to
    `VAs-12.01 Road traffic accident` or `VAs-12.02 Other transport accident`
- `docs/icd-causegrp-mappings/archive/migration-artifacts/who-2022-va-icd-cod-2026-04-27/CMEA10_Blank_WHO_2022_Assignable_Audit_decision.xlsx`
  - reviewed source for codes disabled from WHO 2022 coding assignability

The migration should read from this folder only. Source/review workbooks outside
this folder may continue to evolve.
