---
title: SmartVA Mental Confusion Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
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
| adult confusion-present path | downstream `adult_2_78 -> a2_78` family | `s98` | retained as `Experienced a period of confusion in the three months prior to death` |
| adult confusion-duration path | downstream `adult_2_79 -> a2_79` family | `s99` | retained as `Period of confusion for at least 4 days` |
| adult sudden-confusion path | downstream `adult_2_80 -> a2_80` family | `s100` | retained as `Sudden confusion` |
| `Id10476` contains mental/confusion terms | `adult_7_c -> a7_01` | `s9999111` and related words | weak narrative word lane |

### Adult Summary

The adult confusion family clearly exists in the tariff-applied symptom model:

- `s98` confusion present
- `s99` confusion duration
- `s100` sudden confusion

Important current-state caveat:

The downstream adult PHMRC/SmartVA family is explicit, but the WHO-side adapter wiring for `Id10212` and `Id10213*` is less explicit in this fork than for simpler families like puffiness or jaundice duration.

So the safe current-state reading is:

1. adult mental confusion definitely survives as a structured symptom family
2. duration and sudden-onset features definitely exist downstream
3. the exact one-to-one WHO-field adapter path is less explicit than the downstream symptom model
4. narrative text adds only a weaker generic `mental` word lane

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| no direct child mental-confusion family in the current WHO adapter | child neurologic findings are represented elsewhere |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| child neurologic findings | child unconsciousness / convulsions / stiff-neck families | no direct child mental-confusion tariff family | represented through other neurologic families rather than a direct confusion family |

### Child Summary

The child pipeline does not currently expose a direct mental-confusion family analogous to the adult one.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| no direct neonatal mental-confusion family in the current WHO adapter | neonatal neurologic findings are represented elsewhere |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| neonatal neurologic findings | neonatal unresponsive / convulsions / lethargy families | no direct neonatal mental-confusion tariff family | represented through other neonatal neurologic families rather than a direct confusion family |

### Neonate Summary

The neonate pipeline does not currently expose a direct mental-confusion family.

## Current-State Takeaways

- adult mental confusion: structured three-part family plus a weak narrative word lane
- child mental confusion: no direct confusion family in the current tariff path
- neonate mental confusion: no direct confusion family in the current tariff path
- adult confusion is not collapsed into one single SmartVA variable before tariff application

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Unconsciousness](unconsciousness.md)
- [SmartVA Symptom KB](README.md)
