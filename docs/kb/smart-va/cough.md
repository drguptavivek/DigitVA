---
title: SmartVA Cough Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Cough

This document traces the WHO cough question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Fever](fever.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10153` | Cough |
| duration field(s) for cough | Duration of cough |
| `Id10155` | Cough productive with sputum |
| `Id10157` | Coughed up blood |
| `Id10159` | Difficulty breathing / breathlessness |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10153` | `adult_2_32 -> a2_32` | `s49` | retained as cough |
| duration field(s) | `adult_2_33 -> a2_33` | `s50` | retained as separate cough-duration feature |
| `Id10155` | `adult_2_34 -> a2_34` | `s51` | retained as sputum-producing cough |
| `Id10157` | `adult_2_35 -> a2_35` | `s52` | retained as coughing blood |
| `Id10159` | `adult_2_36 -> a2_36` | `s53` | separate respiratory feature, not cough itself |
| `Id10476` contains `cough` | `adult_7_c -> a7_01` | `s999946` | narrative word lane |

### Adult Summary

Adult cough is not one single downstream SmartVA feature.

Current adult cough family includes:

- `s49` cough
- `s50` cough duration
- `s51` sputum-producing cough
- `s52` coughing blood
- `s53` difficulty breathing
- `s999946` word_cough from narrative text

There is no adult cough keyword path comparable to adult fever.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10153` | Cough |
| `Id10154_a / Id10154_b` | Duration of cough |
| `Id10156` | Cough was severe |
| post-cough vomiting field | Vomited after cough |
| `Id10159` | Difficulty breathing |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10153` | `child_4_12 -> c4_12` | `s121` | retained as cough |
| `Id10154_a / Id10154_b` | `child_4_13 / child_4_13a -> c4_13` | `s122` | retained as separate cough-duration feature |
| `Id10156` | `child_4_14 -> c4_14` | `s123` | retained as very severe cough |
| post-cough vomiting question | `child_4_15 -> c4_15` | `s124` | retained as a cough-associated feature |
| `Id10159` | `child_4_16 -> c4_16` | `s125` | separate respiratory feature |
| `Id10476` contains `cough` | `child_6_c -> c6_01` | `s999913` | narrative word lane |

### Child Summary

Child cough behaves similarly to adult cough:

- several structured cough features survive separately
- narrative cough becomes a separate word feature
- there is no child cough keyword lane in the current keyword list

## Neonate

### WHO Question Group

The current neonatal `smart-va-pipeline` does not expose cough as a first-class symptom family in the same way as adult and child.

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| neonatal respiratory / infection questions | various neonatal variables | respiratory and infection features such as pneumonia / respiratory distress | represented through other neonatal concepts |
| `Id10476` narrative | `child_6_c -> c6_01` | no neonatal `word_cough` feature seen | no neonatal narrative cough lane identified |
| `Id10479` keywords | `neonate_6_* -> n_6_*` | no cough keyword exists | no neonatal cough keyword lane |

### Neonate Summary

Neonatal SmartVA currently does not appear to model a generic cough symptom directly.

Instead, neonatal respiratory signal is represented through other features, such as:

- pneumonia-related terms
- respiratory distress-related terms
- lung-problem-related terms

## Current-State Takeaways

- adult cough: split structured family plus separate narrative word feature
- child cough: split structured family plus separate narrative word feature
- neonate cough: not a first-class symptom family in the current pipeline

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
