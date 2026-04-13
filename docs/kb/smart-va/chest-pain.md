---
title: SmartVA Chest Pain Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Chest Pain

This document traces the WHO chest-pain question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Breathing Difficulty](breathing-difficulty.md)
- [Risk Factors](risk-factors.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10174` | Chest pain |
| `Id10175` | Chest pain severe |
| `Id10176` | Days before death the chest pain remained |
| `Id10179` | Chest pain lasted for in hours |
| `Id10179_1` | Chest pain lasted for in days |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10174` | `adult_2_43 -> a2_43` | `s61` | retained as chest pain in the month preceding death |
| PHMRC chest-pain duration bucket | `adult_2_44 -> a2_44` | `s62` | transformed into `pain greater than 24 hours` |
| PHMRC pain-during-activity flag | `adult_2_45 -> a2_45` | `s63` | retained as pain during physical activity |
| PHMRC chest-pain location | `adult_2_46 -> a2_46a -> s64` | `s64991` / `s64992` | transformed into location bins: chest vs left arm |
| `Id10476` contains `chest` / `pain` | `adult_7_c -> a7_01` | generic word features such as `s999935` and `s9999119` | weak narrative word lane |

### Adult Summary

Adult chest pain is represented as a structured symptom family, not a single variable.

What is clearly retained downstream:

- `s61` chest pain present
- `s62` pain greater than 24 hours
- `s63` pain during physical activity
- `s64991` / `s64992` pain location bins

Important current-state caveat:

The adapter clearly wires `Id10174` into `s61`, but the WHO-side mapping for the other chest-pain subfields is less explicit in this fork than the downstream PHMRC symptom model.

So the safe current-state reading is:

1. chest pain presence definitely survives
2. duration / activity / location features definitely exist downstream
3. those downstream features are part of the adult chest-pain family used by tariffs
4. the exact WHO-field-to-PHMRC wiring for every chest-pain follow-up is less explicit than for simpler families like fever or puffiness

There is no dedicated chest-pain keyword checklist path in the current WHO adapter. Narrative text can still emit generic `chest` and `pain` word features, but that is a weaker and less specific lane than the structured adult chest-pain family.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| no direct child chest-pain family in the current WHO adapter | child respiratory/chest findings are represented elsewhere |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| child chest-related findings | child respiratory families such as breathing difficulty and chest in-drawing | no direct child chest-pain tariff family | represented through other respiratory features rather than chest pain |

### Child Summary

The child pipeline does not currently expose a direct chest-pain symptom family analogous to the adult one.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| no direct neonatal chest-pain family in the current WHO adapter | neonatal chest-related findings are represented elsewhere |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| neonatal chest-related findings | neonatal respiratory / physical-abnormality families | no direct neonatal chest-pain tariff family | represented through other neonatal families rather than chest pain |

### Neonate Summary

The neonate pipeline does not currently expose a direct chest-pain symptom family.

## Current-State Takeaways

- adult chest pain: structured multi-feature family plus a weak generic narrative word lane
- child chest pain: no direct chest-pain family in the current tariff path
- neonate chest pain: no direct chest-pain family in the current tariff path
- adult chest pain is not collapsed into one single SmartVA variable before tariff application

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Breathing Difficulty](breathing-difficulty.md)
- [SmartVA Symptom KB](README.md)
