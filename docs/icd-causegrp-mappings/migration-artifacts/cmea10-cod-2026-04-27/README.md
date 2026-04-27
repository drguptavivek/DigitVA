---
title: CMEA10 COD Migration Artifacts
doc_type: migration-artifact
status: active
owner: engineering
last_updated: 2026-04-27
---

# CMEA10 COD Migration Artifacts

This folder contains the fixed CMEA10 COD bucket source workbook for migration
use.

Files:

- `icd-10-CODES_CMEA10_mapped.xlsx`
  - CMEA10 source workbook
  - rows with blank `CMEA10` values are intentionally not imported as mappings

Migrations should read this copy, not the working source workbook under
`ICD-to-VA-Buckets`.
