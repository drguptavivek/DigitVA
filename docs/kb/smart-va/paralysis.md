---
title: SmartVA Paralysis Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Paralysis

This document traces the WHO paralysis question block `Id10258` through `Id10260` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Unconsciousness](unconsciousness.md)
- [Mental Confusion](mental-confusion.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10258` | Paralysis |
| paralysis duration field(s) | duration before death |
| `Id10259` | Paralysis of only one side of the body |
| `Id10260` | Paralysis of both legs |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10258` | `adult_2_85 -> a2_85` | `s105` | retained as paralyzed |
| duration detail | downstream `adult_2_86 -> a2_86` family | `s106` | separate duration feature exists downstream |
| paralysis location detail | `adult_2_87 -> a2_87_*` | `s107`, `s109`, `s110`, `s111`, `s112`, `s113`, `s114`, `s115`, `s116` | transformed into location-specific paralysis family |
| `Id10476` contains paralysis terms | `adult_7_c -> a7_01` | `s9999120` | narrative paralysis word lane |

### Adult Summary

The adult paralysis block becomes a broad structured family:

- `s105` paralysis present
- `s106` paralysis duration
- location-specific splits such as one-sided, lower body, upper body, one leg, one arm, whole body, and other

Important current-state caveat:

The downstream location family is explicit, but the WHO 2022 adapter path for every location detail is less cleanly expressed than the downstream PHMRC-style symptom model. So the safe reading is that the adult paralysis family definitely exists, while some of the fine WHO-field-to-location wiring is adapter-shaped rather than fully transparent.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10258` through `Id10260` | paralysis block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10258` through `Id10260` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline does not expose a direct paralysis family from this WHO block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10258` through `Id10260` | paralysis block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10258` through `Id10260` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not expose a direct paralysis family from this WHO block.

## Current-State Takeaways

- adult paralysis: structured presence, duration, and location family plus a narrative paralysis word lane
- child paralysis: this WHO block is not used in the current tariff path
- neonate paralysis: this WHO block is not used in the current tariff path
