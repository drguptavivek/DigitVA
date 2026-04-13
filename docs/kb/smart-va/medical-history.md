---
title: SmartVA Medical History Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Medical History

This document traces the WHO medical-history question block `Id10125` through `Id10144` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Fever](fever.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10125` | Tuberculosis |
| `Id10126` | HIV |
| `Id10127` | AIDS |
| `Id10128` | Tested positive for malaria |
| `Id10129` | Tested negative for malaria |
| `Id10130` | Dengue fever |
| `Id10131` | Measles |
| `Id10132` | High blood pressure |
| `Id10133` | Heart disease |
| `Id10134` | Diabetes |
| `Id10135` | Asthma |
| `Id10136` | Epilepsy |
| `Id10137` | Cancer |
| `Id10138` | Chronic Obstructive Pulmonary Disease (COPD) |
| `Id10139` | Dementia |
| `Id10140` | Depression |
| `Id10141` | Stroke |
| `Id10142` | Sickle cell disease |
| `Id10143` | Kidney disease |
| `Id10144` | Liver disease |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10135` | `adult_1_1a -> a1_01_1` | `s1` | retained as previous diagnosis of asthma |
| `Id10137` | `adult_1_1c -> a1_01_3` | `s3` | retained as previous diagnosis of cancer |
| `Id10138` | `adult_1_1m -> a1_01_4` | `s4` | retained as previous diagnosis of COPD |
| `Id10134` | `adult_1_1g -> a1_01_7` | `s7` | retained as previous diagnosis of diabetes |
| `Id10136` | `adult_1_1h -> a1_01_8` | `s8` | retained as previous diagnosis of epilepsy |
| `Id10133` | `adult_1_1i -> a1_01_9` | `s9` | retained as previous diagnosis of heart disease |
| `Id10141` | `adult_1_1l -> a1_01_12` | `s12` | retained as previous diagnosis of stroke |
| `Id10125` | `adult_1_1d -> a1_01_13` | `s13` | retained as previous diagnosis of TB |
| `Id10127` | `adult_1_1n -> a1_01_14` | `s14` | retained as previous diagnosis of AIDS |
| `Id10126` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10128` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10129` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10130` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10131` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10132` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10139` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10140` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10142` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10143` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |
| `Id10144` | no WHO-to-PHMRC mapping in the current adult adapter | none | ignored before symptom/tariff stages |

### Adult Summary

This WHO block is partly retained for adults, but only for a narrow subset of diagnoses.

What is retained as tariff-applied adult history features:

- asthma
- cancer
- COPD
- diabetes
- epilepsy
- heart disease
- stroke
- TB
- AIDS

What is currently ignored from `Id10125` through `Id10144`:

- HIV
- malaria test results
- dengue
- measles
- high blood pressure
- dementia
- depression
- sickle cell disease
- kidney disease
- liver disease

The retained diagnoses do not first become adult symptom-family questions like fever or cough. They go through the adult history checklist path:

1. WHO diagnosis question
2. `adult_1_1*` PHMRC-style history variable
3. `a1_01_*` pre-symptom history slot
4. tariff-applied adult history feature `s1` to `s14`

So this block is mostly a `retained-or-ignored` history path, not a transformed duration/bucketing path.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10125` through `Id10144` | medical-history block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10125` through `Id10144` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline does not currently use the `Id10125` through `Id10144` WHO medical-history block as a child history/tariff feature family.

Child early-history features exist in the smart-va-pipeline, but they come from other WHO sections, not this adult-style medical-history block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10125` through `Id10144` | medical-history block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10125` through `Id10144` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not currently use the `Id10125` through `Id10144` WHO medical-history block in its tariff path.

## Current-State Takeaways

- adult medical history: partly retained, mostly as direct previous-diagnosis features
- child medical history: this WHO block is not used in the current tariff path
- neonate medical history: this WHO block is not used in the current tariff path
- this is a selective retention path, not a broad one-to-one import of WHO diagnosis history

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [SmartVA Symptom KB](README.md)
