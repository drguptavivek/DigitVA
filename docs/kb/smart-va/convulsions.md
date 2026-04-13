---
title: SmartVA Convulsions Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Convulsions

This document traces the WHO convulsions question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Unconsciousness](unconsciousness.md)
- [Breathing Difficulty](breathing-difficulty.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10220` | Generalized convulsions |
| duration field(s) for convulsions | Duration of convulsions |
| `Id10222` | Unconscious immediately after the convulsion |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10220` | `adult_2_82 -> a2_82` | `s102` | retained as convulsions |
| duration field(s) | `adult_2_83 -> a2_83` | `s103` | separate duration feature |
| `Id10222` | `adult_2_84 -> a2_84` | `s104` | retained as unconscious after convulsions |
| `Id10476` narrative contains convulsion terms | `adult_7_c -> a7_01` | convulsion-related word features | narrative word lane |

### Adult Summary

Adult convulsions are modeled as a compact three-part structured family plus a narrative word lane.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10220` | Generalized convulsions |
| `Id10275` | Convulsions started first 24 hours of life |
| `Id10276` | Convulsions started more than 24 hours after birth |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10220` | `child_4_25 -> c4_25` | `s133` | retained as generalized convulsions or fits |
| immediate age / timing context | child/neonatal timing fields | age-specific timing interpretation rather than a separate child tariff feature | partial age-context handling |
| `Id10476` narrative contains convulsion terms | `child_6_c -> c6_01` | `s999912` and related words | narrative word lane |

### Child Summary

Child convulsions are simpler than adult convulsions in the tariff layer: one main structured convulsion feature plus narrative signal.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| neonatal convulsions question feeding `c3_25` | Spasms or convulsions |
| `Id10476` | Narration |
| `Id10479` | Neonatal narration keywords |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| convulsions question | `c3_25` | `s86` | retained as spasms or convulsions |
| `Id10476` narrative | `child_6_c -> c6_01` | no dedicated neonatal convulsion keyword path identified | limited narrative role |
| `Id10479` keywords | `neonate_6_*` | no convulsion keyword exists | no neonatal keyword lane |

### Neonate Summary

Neonate convulsions are represented by one direct structured feature: `s86`.

## Current-State Takeaways

- adult convulsions: structured family plus narrative word lane
- child convulsions: one main structured feature plus narrative signal
- neonate convulsions: one structured feature only

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
