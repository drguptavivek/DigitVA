---
title: SmartVA Stiff Neck Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Stiff Neck

This document traces the WHO stiff or painful neck question block `Id10208` and `Id10209*` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Convulsions](convulsions.md)
- [Unconsciousness](unconsciousness.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10208` | Stiff or painful neck? |
| `Id10209` | Duration of stiff or painful neck in days |
| `Id10209_b` | Duration of stiff or painful neck in months |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10208` | `adult_2_72 -> a2_72` | `s92` | retained as stiff neck |
| duration detail | downstream `adult_2_73 -> a2_73` family | `s93` | separate duration feature exists downstream |
| `Id10476` contains neck-related words | `adult_7_c -> a7_01` | `s9999113` and related words | weak narrative word lane |

### Adult Summary

The adult pipeline clearly retains a structured stiff-neck family:

- `s92` for stiff neck
- `s93` for duration / thresholded duration

Important current-state caveat:

The downstream adult symptom family is explicit, but the WHO-side adapter wiring for `Id10209` and `Id10209_b` is less explicit in this fork than the downstream symptom model. So the safe reading is:

1. `Id10208` definitely survives as `s92`
2. a separate duration feature `s93` definitely exists downstream
3. the exact WHO 2022 duration-field adapter path is less explicit than the downstream symptom family

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10208` | Stiff or painful neck? |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10208` | `child_4_28 -> c4_28` | `s136` | retained as stiff neck |
| `Id10476` narrative | `child_6_c -> c6_01` | `s999932` and related words | weak narrative word lane |

### Child Summary

The child pipeline retains one direct structured stiff-neck feature: `s136`.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10208` and `Id10209*` | stiff-neck block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10208` and `Id10209*` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not expose a direct stiff-neck family from this WHO block.

## Current-State Takeaways

- adult stiff neck: structured family plus a weak narrative word lane
- child stiff neck: one direct structured feature plus a weak narrative word lane
- neonate stiff neck: this WHO block is not used in the current tariff path
- adult and child stiff-neck evidence is not collapsed into one shared cross-age variable; each age group has its own symptom namespace
