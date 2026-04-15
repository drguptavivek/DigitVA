---
title: SmartVA Nutrition Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Nutrition

This document traces the `General Symptoms / nutrition` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Swelling](swelling.md)
- [Skin Other](skin-other.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10268` | Look pale or have pale palms, eyes or nail beds |
| `Id10269` | Sunken eyes |
| `Id10252` | General swelling of the body |
| `Id10485` | Extreme fatigue |

## Forward Trace

### Adult

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10252` | `adult_2_27 -> a2_27` | `s44` | retained as general puffiness all over the body |
| `Id10268` | none | none | not retained in the adult path |
| `Id10269` | none | none | not retained in the adult path |
| `Id10485` | none | none | not retained in the adult path |

### Child

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10268` | `child_4_41 -> c4_41` | `s150` | retained as pallor / lack-of-blood symptom |
| `Id10252` | none | none | not retained in the child path |
| `Id10269` | none | none | not retained in the child path |
| `Id10485` | none | none | not retained in the child path |

### Neonate

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| nutrition block `Id10268`, `Id10269`, `Id10252`, `Id10485` | no neonate WHO-to-PHMRC mapping in this block | none | ignored for neonate tariff scoring |

## Current-State Summary

This displayed WHO subcategory does not stay together as one SmartVA concept.

What survives:

- adult `Id10252 -> s44` as general body puffiness
- child `Id10268 -> s150` as pallor / lack of blood

What does not survive as a first-class SmartVA feature from this displayed block:

- `Id10269` sunken eyes
- `Id10485` extreme fatigue
- adult pallor from `Id10268`
- child general swelling from `Id10252`

## Important Caveat

The UI grouping `nutrition` is broader than the current SmartVA adapter.

The retained pieces are split across different downstream symptom families:

1. adult `Id10252` behaves like a swelling / puffiness feature
2. child `Id10268` behaves like a pallor feature
3. the rest of the visible questions are ignored in the current pipeline

## Code Map

- [Swelling](swelling.md)
- [Skin Other](skin-other.md)
