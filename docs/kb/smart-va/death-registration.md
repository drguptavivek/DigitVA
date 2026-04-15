---
title: SmartVA Death Registration Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Death Registration

This document traces the `Narration / Documents / death_registeration` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Medical Certificates](medical-certs.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10070` | Death registration number/certificate |
| `Id10071` | Date of death registration |
| `Id10072` | Place of death registration |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10070`, `Id10071`, `Id10072` | no direct WHO-to-PHMRC mapping | none | ignored before symptom and tariff stages |

## Current-State Summary

This displayed death-registration block is metadata only for current SmartVA behavior.

It does not feed:

- symptom-stage variables
- tariff-applied variables
- free-text word processing

## Important Caveat

These fields are not currently dropped out of the prepared SmartVA input in the same special way that `sa*` fields are. But they also do not have a downstream adapter path.

So the safe current-state reading is:

1. they remain questionnaire metadata
2. they are not used by SmartVA scoring
3. they do not create open-response word features

## Code Map

- [Medical Certificates](medical-certs.md)
