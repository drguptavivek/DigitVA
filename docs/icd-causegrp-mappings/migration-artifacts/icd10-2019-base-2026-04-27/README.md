---
title: ICD10 2019 Base Migration Artifacts
doc_type: migration-artifact
status: active
owner: engineering
last_updated: 2026-04-27
---

# ICD10 2019 Base Migration Artifacts

This folder contains fixed inputs for ICD-10 2019 base hierarchy migrations.

Files:

- `icd102019en.xml`
  - source WHO ICD-10 2019 XML used to generate the hierarchy CSV
- `icd10_2019_hierarchy.csv`
  - generated hierarchy CSV imported into `mas_icd10_2019_2`
  - includes generated dotted detailed rows from ICD XML modifier classes

Migrations should import the CSV from this folder. The XML is retained as the
source reference for auditability and regeneration, but Alembic migrations
should not parse XML at runtime.
