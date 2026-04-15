---
title: SmartVA Health Service Treatment Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Health Service Treatment

This document traces the `Health Service Utilisation / treatment` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Health Service HCW Cause Of Death](health-service-hcw-cod.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10418` | Received any treatment for the illness that led to death |
| `Id10419` | Receive oral rehydration salts |
| `Id10420` | Received (or need) intravenous fluids (drip) treatment |
| `Id10421` | Received (or need) a blood transfusion |
| `Id10422` | Received (or need) treatment/food through a tube passed through the nose |
| `Id10423` | Received (or need) injectable antibiotics |
| `Id10424` | Received (or need) antiretroviral therapy (ART) |
| `Id10425` | Have (or need) an operation for the illness |
| `Id10426` | Operation within 1 month before death |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10418` to `Id10426` | no direct WHO-to-PHMRC mapping from this displayed subcategory | none | ignored before symptom and tariff stages |

## Current-State Summary

This displayed treatment block does not feed first-class SmartVA symptoms in the current WHO adapter.

None of the visible treatment-utilisation questions in this subcategory reach:

- symptom-stage `s...` variables
- tariff-applied features
- free-text word processing

## Important Caveat

The current SmartVA pipeline does use older health-care-experience fields, but not from this displayed WHO 2022 treatment block.

The retained HCE path instead comes from other non-displayed or older fields such as:

- `Id10432`
- `Id10437`
- `Id10438`
- `Id10444`

So the safe current-state reading is:

1. this displayed subcategory is operationally useful in the questionnaire
2. it is not currently used by SmartVA scoring
3. SmartVA still has a separate older HCE path outside this visible block

## Code Map

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
