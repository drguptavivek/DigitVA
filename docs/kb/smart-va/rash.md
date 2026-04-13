---
title: SmartVA Rash Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Rash

This document traces the WHO rash and skin-eruption question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Swelling](swelling.md)
- [Jaundice](jaundice.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10233` | Skin rash |
| duration field(s) for skin rash | Duration of skin rash |
| `Id10235` | Location of skin rash |
| `Id10236` | Measles rash |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10233` | `adult_2_7 -> a2_07` | `s21` | retained as rash |
| duration field(s) | intended `adult_2_8 -> a2_08` | `s22` | treated as separate rash-duration feature when present |
| `Id10235` | `adult_2_9 -> a2_09` | `s23 -> s23991 / s23992 / s23993 / s23994` | transformed into rash-location bins |
| `Id10236` and related skin features | `adult_2_10+` | `s27+` family | related skin features remain separate from the core rash feature |
| `Id10476` narrative contains rash-related words | `adult_7_c -> a7_01` | skin-related word features | narrative word lane |

### Adult Summary

Adult rash remains a structured skin family with separate duration and location handling.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10233` | Skin rash |
| `Id10234` | Duration of skin rash |
| `Id10235` | Location of skin rash |
| `Id10236` | Measles rash |
| `Id10238` | Skin flake off in patches |
| `Id10478:rash` | Narration keyword: rash |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10233` | `child_4_30 -> c4_30` | `s138` | retained as rash |
| `Id10235` / location path | `child_4_31 -> c4_31` | `s139 -> s139991` | transformed into rash-location signal |
| `Id10234` | `child_4_33 -> c4_33` | `s142` | retained as rash-duration feature |
| blister / vesicle path | `child_4_34 -> c4_34` | `s143` | retained as rash subtype |
| `Id10238` | `child_4_38 -> c4_38` | `s147` | separate skin-flaking feature |
| hair-color change | `child_4_39 -> c4_39` | `s148` | separate skin/nutrition-related feature |
| `Id10476` narrative | `child_6_c -> c6_01` | skin-related word features | narrative word lane |
| `Id10478:rash` | `child_6_10 -> c_6_10` | rash-related word feature | keyword lane |

### Child Summary

Child rash has a richer downstream structure than adult, with explicit duration, location, blistering, and related skin features.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| neonatal skin-pus / ulcer / redness questions | neonatal skin infection signs |
| `Id10476` | Narration |
| `Id10479` | Neonatal narration keywords |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| pus / skin bumps question | `c3_38 / c3_39` paths | `s99 / s100+` family | neonatal skin-infection family |
| redness / swelling question | `c3_37` path | `s98` | retained as redness spreading onto abdominal skin |
| `Id10476` narrative | `child_6_c -> c6_01` | no dedicated neonatal rash word lane identified | weak narrative path |
| `Id10479` keywords | `neonate_6_*` | no rash keyword exists | no neonatal rash keyword lane |

### Neonate Summary

Neonate does not mirror adult/child rash handling. The pipeline focuses on skin infection, pus, ulcer, and redness signals rather than a generic rash feature.

## Current-State Takeaways

- adult rash: structured family with duration and location bins
- child rash: richer structured family plus narrative/keyword lanes
- neonate rash: skin-infection-focused family rather than a generic rash feature

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
