---
title: WHO 2022 VA ICD And COD Migration Artifacts
doc_type: migration-artifact
status: active
owner: engineering
last_updated: 2026-04-27
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
  - intentionally remains broader than assignability because non-assignable
    codes do not need to be removed from reporting bucket documentation
- `CMEA10_Blank_WHO_2022_Assignable_Audit_decision.xlsx`
  - reviewed source for codes disabled from WHO 2022 coding assignability

The migration should read from this folder only. Source/review workbooks outside
this folder may continue to evolve.
