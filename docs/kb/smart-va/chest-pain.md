---
title: SmartVA Chest Pain Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
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
| `Id10178` | Hidden helper used by the SmartVA prep for chest-pain duration in minutes |
| `Id10179` | Chest pain lasted for in hours |
| `Id10179_1` | Chest pain lasted for in days |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10174` | `adult_2_43 -> a2_43` | `s61` | retained as chest pain in the month preceding death |
| `Id10178`, `Id10179`, `Id10179_1` | `who_prep.map_adult_chest_pain_duration() -> adult_2_44 -> a2_44` | `s62` | explicit WHO prep path for chest-pain duration; only the `>24 hours` bucket is tariff-positive |
| downstream adult chest-pain activity feature | `adult_2_45 -> a2_45` | `s63` | exists in the adult SmartVA model, but no visible WHO 2022 source mapping is surfaced in this fork |
| downstream adult chest-pain location feature | `adult_2_46 -> a2_46a -> s64` | `s64991` / `s64992` | exists in the adult SmartVA model, but no visible WHO 2022 source mapping is surfaced in this fork |
| `Id10175`, `Id10176` | no explicit WHO 2022 mapping to `adult_2_45` or `adult_2_46` | none from the visible WHO block | not visibly retained as first-class inputs in this fork |
| `Id10476` contains `chest` / `pain` | `adult_7_c -> a7_01` | generic word features such as `s999935` and `s9999119` | weak narrative word lane |

### Adult Summary

For the current WHO 2022 adapter, the adult chest-pain family is narrower than the downstream adult SmartVA model.

What is explicitly wired from visible WHO fields:

- `Id10174 -> s61`
- `Id10178` / `Id10179` / `Id10179_1 -> s62`

What exists downstream but is not visibly fed from the WHO 2022 chest-pain block in this fork:

- `s63` pain during physical activity
- `s64991` / `s64992` chest-pain location bins

So the current adult WHO 2022 path keeps chest-pain presence and duration, while the richer downstream activity/location features depend on non-visible or older sources not surfaced here.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| no direct child chest-pain family in the current WHO adapter | child respiratory/chest findings are represented elsewhere |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| child chest-related findings | child respiratory families such as breathing difficulty and chest in-drawing | no direct child chest-pain tariff family | represented through other respiratory features rather than chest pain |

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| no direct neonatal chest-pain family in the current WHO adapter | neonatal chest-related findings are represented elsewhere |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| neonatal chest-related findings | neonatal respiratory / physical-abnormality families | no direct neonatal chest-pain tariff family | represented through other neonatal families rather than chest pain |

## Current-State Takeaways

- adult chest pain: explicit WHO retention for presence and duration only
- adult activity/location features exist in the SmartVA model but are not visibly fed by the WHO 2022 chest-pain block in this fork
- child chest pain: no direct chest-pain family in the current tariff path
- neonate chest pain: no direct chest-pain family in the current tariff path

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Breathing Difficulty](breathing-difficulty.md)
- [SmartVA Symptom KB](README.md)
