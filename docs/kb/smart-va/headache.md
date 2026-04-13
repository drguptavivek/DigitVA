---
title: SmartVA Headache Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Headache

This document traces the WHO severe-headache question block around `Id10207` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Stiff Neck](stiff-neck.md)
- [Mental Confusion](mental-confusion.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10207` | Severe headache |
| headache duration field(s) | duration before death |
| headache onset field | rapid vs slow onset |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| headache-present path | downstream `adult_2_69 -> a2_69` family | `s89` | retained as headaches |
| headache-duration path | downstream `adult_2_70 -> a2_70` family | `s90` | retained as thresholded duration |
| headache-onset path | downstream `adult_2_71 -> a2_71` family | `s91` | transformed into rapid-headache onset |
| `Id10476` narrative | `adult_7_c -> a7_01` | no strong dedicated headache word feature identified | limited narrative role |

### Adult Summary

The adult headache family clearly exists in the downstream symptom and tariff layers:

- `s89` headaches
- `s90` headache duration
- `s91` rapid onset

Important current-state caveat:

The downstream family is explicit, but the WHO-side adapter wiring for the full headache block is less explicit in this fork than for cleaner families like swallowing or protruding abdomen.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10207` and nearby headache block | severe-headache family |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10207` and nearby headache block | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline does not expose a direct headache family from this WHO block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10207` and nearby headache block | severe-headache family |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10207` and nearby headache block | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not expose a direct headache family from this WHO block.

## Current-State Takeaways

- adult headache: structured three-part family downstream
- child headache: this WHO block is not used in the current tariff path
- neonate headache: this WHO block is not used in the current tariff path
