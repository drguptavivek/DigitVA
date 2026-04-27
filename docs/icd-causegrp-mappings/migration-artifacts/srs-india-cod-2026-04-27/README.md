---
title: SRS India COD Migration Artifacts
doc_type: migration-artifact
status: active
owner: engineering
last_updated: 2026-04-27
---

# SRS India COD Migration Artifacts

This folder contains the fixed SRS India COD bucket source workbook for
migration use.

Files:

- `icd-10-CODES_SRS_India.xlsx`
  - age-scoped SRS India source workbook
  - contains adult, neonate, and child mapping columns consumed by the SRS
    importer

Migrations should read this copy, not the working source workbook under
`ICD-to-VA-Buckets`.
