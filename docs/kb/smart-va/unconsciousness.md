---
title: SmartVA Unconsciousness Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Unconsciousness

This document traces the WHO loss-of-consciousness and unresponsiveness question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Convulsions](convulsions.md)
- [Breathing Difficulty](breathing-difficulty.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10214` | Unconscious |
| `Id10217` | Unconsciousness started suddenly |
| duration field(s) for unconsciousness | Duration of unconsciousness |
| `Id10218` | Unconsciousness continued until death |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10214` | `adult_2_74 -> a2_74` | `s94` | retained as loss of consciousness |
| `Id10217` | `adult_2_75 -> a2_75` | `s95` | retained as sudden loss of consciousness |
| duration field(s) | `adult_2_76 -> a2_76` | `s96` | separate duration feature |
| `Id10218` | `adult_2_77 -> a2_77` | `s97` | continued-until-death feature |
| `Id10476` narrative contains unconsciousness terms | `adult_7_c -> a7_01` | words such as `s999943` | narrative word lane |

### Adult Summary

Adult unconsciousness is a structured family with onset and duration detail.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10214` | Unconscious |
| child timing field for unconsciousness | timing of unconsciousness |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10214` | `child_4_26 -> c4_26` | `s134` | retained as unconsciousness |
| timing field | `child_4_27 -> c4_27` | `s135 -> s135991` | transformed into timing signal |
| `Id10476` narrative | `child_6_c -> c6_01` | consciousness-related word features | narrative word lane |

### Child Summary

Child unconsciousness is represented by a main unconsciousness feature plus a downstream timing transform.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10281` | Baby become unresponsive or unconscious |
| `Id10282` | Unresponsive / unconscious within 24 hours of birth |
| `Id10283` | Unresponsive / unconscious more than 24 hours after birth |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10281` | `child_3_33 -> c3_33` | `s94` | retained as neonatal unresponsive / unconscious |
| timing detail | neonatal age-context fields | timing is represented through age-context logic rather than a large separate family | partial timing handling |
| `Id10476` narrative | `child_6_c -> c6_01` | no strong dedicated unconsciousness word lane identified | limited narrative role |

### Neonate Summary

Neonate unconsciousness is modeled more compactly than adult unconsciousness. The main retained signal is `s94`.

## Current-State Takeaways

- adult unconsciousness: direct structured family with onset and duration detail
- child unconsciousness: direct feature plus timing transform
- neonate unconsciousness: compact direct feature

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
