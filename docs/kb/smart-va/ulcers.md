---
title: SmartVA Ulcers Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Ulcers

This document traces the WHO ulcers and sores question block `Id10227` through `Id10232` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Rash](rash.md)
- [Swelling](swelling.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10227` | Ulcers or sores anywhere else on the body |
| `Id10228` | Ulcers or sores anywhere else on the body had pus |
| `Id10229` | Ulcers or sores anywhere else on body have pus |
| `Id10230` | Ulcer on the foot |
| `Id10231` | Ulcer on foot have pus |
| `Id10232` | Duration of ulcer on the foot had pus in days |
| `Id10232_b` | Duration of ulcer on the foot had pus in months |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10227` | `adult_2_10 -> a2_10` | `s27` | retained as sores |
| `Id10229` | `adult_2_11 -> a2_11` | `s28` | retained as sores had clear fluid or pus |
| `Id10230` | `adult_2_13 -> a2_13` | `s30` | retained as ulcer on the foot |
| `Id10231` | `adult_2_14 -> a2_14` | `s31` | retained as foot ulcer oozed pus |
| `Id10232` / `Id10232_b` | `adult_2_15 -> a2_15` | `s32` | transformed into thresholded duration |
| `Id10476` contains ulcer terms | `adult_7_c -> a7_01` | `s9999158` | narrative ulcer word lane |

### Adult Summary

The adult ulcers block survives as two related structured lanes:

- general sores: `s27`, `s28`
- foot-ulcer family: `s30`, `s31`, `s32`

Important current-state caveat:

The WHO adapter currently overrides `adult_2_10` from `Id10228` to `Id10227`, so the exact distinction between the older pus-specific wording and the current combined WHO sores question is handled through adapter logic rather than a perfectly clean one-to-one mapping.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10227` through `Id10232` | ulcers / sores block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10227` through `Id10232` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline does not expose a direct ulcers family from this WHO block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10227` through `Id10232` | ulcers / sores block |
| `Id10288` | Baby have skin ulcer(s) or sore(s) |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10227` through `Id10232` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |
| neonatal skin-ulcer concept | separate neonatal skin family | `s100` and nearby neonatal skin features | represented elsewhere, not through the adult WHO ulcer block |

### Neonate Summary

The neonate pipeline has skin-ulcer concepts, but not through the adult WHO `Id10227` through `Id10232` path.

## Current-State Takeaways

- adult ulcers: structured sores lane, structured foot-ulcer lane, and a narrative ulcer word lane
- child ulcers: this WHO block is not used in the current tariff path
- neonate ulcers: related neonatal skin findings are represented elsewhere, not through this adult block
- adult ulcer evidence is not collapsed into one single tariff variable before scoring
