---
title: SmartVA Protruding Abdomen Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Protruding Abdomen

This document traces the WHO protruding-abdomen question block `Id10200` through `Id10203` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Abdominal Pain](abdominal-pain.md)
- [Mass Abdomen](mass-abdomen.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10200` | More than usually protruding abdomen |
| `Id10201` | Duration of protruding abdomen in days before death |
| `Id10202` | Duration of protruding abdomen in months before death |
| `Id10203` | Rate of abdominal protrusion development |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10200` | `adult_2_64 -> a2_64` | `s84` | retained as protruding belly |
| `Id10201` / `Id10202` with `Id10201_unit` | `adult_2_65 -> a2_65` | `s85` | transformed into thresholded duration |
| `Id10203` | `adult_2_66 -> a2_66` | `s86` | transformed into rate of development, with tariff-active emphasis on slowly protruding belly |
| `Id10476` contains abdomen terms | `adult_7_c -> a7_01` | `s99991` | generic narrative abdomen word lane |

### Adult Summary

The adult protruding-abdomen family is retained as three separate signals: presence, duration, and development rate.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10200` | More than usually protruding abdomen |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10200` | `child_4_40 -> c4_40` | `s149` | retained as protruding belly |

### Child Summary

The child pipeline retains one direct protruding-belly feature: `s149`.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10200` through `Id10203` | protruding-abdomen block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10200` through `Id10203` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not expose a direct protruding-abdomen family from this WHO block.

## Current-State Takeaways

- adult protruding abdomen: structured presence, duration, and rate family
- child protruding abdomen: one direct protruding-belly feature
- neonate protruding abdomen: this WHO block is not used in the current tariff path
