---
title: SmartVA Medical Documents Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Medical Documents

This document traces the `Narration / Documents / medical_documents` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Medical Certificates](medical-certs.md)

## WHO Subcategory Fields

This subcategory contains attachment slots:

`md_im1` through `md_im30`

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `md_im1` to `md_im30` | no direct WHO-to-PHMRC mapping | none | ignored before symptom and tariff stages |

## Current-State Summary

The medical-document image fields are attachment storage only for current SmartVA behavior.

They do not feed:

- structured SmartVA variables
- free-text word extraction
- tariff-applied symptoms

## Important Caveat

These image slots are not part of the special `_SMARTVA_DROP_PREFIXES` list in DigitVA prep, but they also do not have a downstream mapping path.

So the safe current-state reading is:

1. they exist for document capture and review workflows
2. they do not influence SmartVA scoring
3. they are not OCR'd or text-extracted by the SmartVA path

## Code Map

- [Medical Certificates](medical-certs.md)
