---
title: SmartVA Health Service Mother Related Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Health Service Mother Related

This document traces the `Health Service Utilisation / mother_related` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Health Service HCW Cause Of Death](health-service-hcw-cod.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10446` | Deceased's (biological) mother ever been told she had HIV/AIDS by a health worker |

## Forward Trace

### Child / Neonate

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10446` | `child_5_19 -> c5_19` | `s190` | retained as maternal AIDS / HIV-history feature in child and neonate scoring |

### Adult

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10446` | no adult WHO-to-PHMRC mapping | none | ignored in adult scoring |

## Current-State Summary

This displayed subcategory is narrow and clean in the current pipeline.

What survives:

- child `s190`
- neonate `s190`

What does not happen:

- no adult SmartVA path uses this field
- no free-text or collapsed branch is involved here

## Important Caveat

This field is part of the child / neonate health-service family, not a general all-age health-history feature.

So the safe current-state reading is:

1. it matters only for child and neonate SmartVA runs
2. it is retained as a direct symptom-style HIV-context feature
3. it does not affect adult SmartVA scoring

## Code Map

- [Health Service HCW Cause Of Death](health-service-hcw-cod.md)
