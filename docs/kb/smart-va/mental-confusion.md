---
title: SmartVA Mental Confusion Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Mental Confusion

This document traces the WHO mental-confusion question block `Id10212` and `Id10213*` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Unconsciousness](unconsciousness.md)
- [Convulsions](convulsions.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10212` | Mental confusion |
| `Id10213_a` | Duration of mental confusion in days |
| `Id10213` | Duration of mental confusion in months |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| adult confusion family in the downstream model | `adult_2_78 -> a2_78` | `s98` | the adult SmartVA model has a structured confusion-present feature |
| adult confusion duration family in the downstream model | `adult_2_79 -> a2_79a/a2_79b -> a2_79` | `s99` | the adult SmartVA model has a thresholded confusion-duration feature |
| adult confusion onset family in the downstream model | `adult_2_80 -> a2_80` | `s100` | the adult SmartVA model has a sudden-confusion feature |
| visible WHO fields `Id10212`, `Id10213_a`, `Id10213` | no explicit `who_data.py` or `who_prep.py` mapping to `adult_2_78`, `adult_2_79`, or `adult_2_80` in this fork | none from the visible WHO 2022 block | not visibly wired from the displayed WHO block |
| `Id10476` contains mental/confusion terms | `adult_7_c -> a7_01` | `s9999111` and related words | weak narrative word lane |

## Child

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| child neurologic findings | child unconsciousness / convulsions / stiff-neck families | no direct child mental-confusion tariff family | represented through other neurologic families rather than a direct confusion family |

## Neonate

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| neonatal neurologic findings | neonatal unresponsive / convulsions / lethargy families | no direct neonatal mental-confusion tariff family | represented through other neonatal neurologic families rather than a direct confusion family |

## Current-State Takeaways

- the adult SmartVA model includes a three-part confusion family: `s98`, `s99`, `s100`
- the visible WHO 2022 confusion block does not show an explicit adapter path into that family in this fork
- child and neonate do not expose a direct confusion family from this WHO block

So the current-state answer is narrower than the second-pass doc: the downstream adult family exists, but the visible WHO 2022 block is not explicitly wired into it here.

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Unconsciousness](unconsciousness.md)
- [SmartVA Symptom KB](README.md)
