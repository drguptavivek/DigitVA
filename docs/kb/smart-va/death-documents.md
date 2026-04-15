---
title: SmartVA Death Documents Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Death Documents

This document traces the `Narration / Documents / death_documents` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Death Registration](death-registration.md)

## WHO Subcategory Fields

This subcategory contains attachment slots:

`ds_im1` through `ds_im5`

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `ds_im1` to `ds_im5` | no direct WHO-to-PHMRC mapping | none | ignored before symptom and tariff stages |

## Current-State Summary

The death-document image fields are attachment storage only for current SmartVA behavior.

They do not feed:

- structured SmartVA variables
- free-text word extraction
- tariff-applied symptoms

## Important Caveat

These image slots are retained in the broader DigitVA submission payload for review workflows, but they are not interpreted by the SmartVA adapter.

So the safe current-state reading is:

1. they support document capture and review
2. they do not affect SmartVA scoring
3. they are not OCR'd or text-extracted by the SmartVA path

## Code Map

- [Death Registration](death-registration.md)
