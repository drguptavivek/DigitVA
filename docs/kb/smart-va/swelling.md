---
title: SmartVA Swelling Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Swelling

This document traces the WHO swelling, edema, and puffiness question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Jaundice](jaundice.md)
- [Rash](rash.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10247` | Puffiness of face |
| `Id10248_a` | Duration of puffiness of the face in days |
| `Id10248_b` | Duration of puffiness of the face in months |
| `Id10248_units` | Units helper for puffiness duration |
| `Id10252` | General swelling of the body |
| `Id10249` | Swollen legs or feet |
| `Id10250` | Duration of swelling lasted in days |
| `Id10250_b` | Duration of swelling lasted in months |
| `Id10250_units` | Units helper for leg/feet swelling duration |
| `Id10251` | Both feet swollen |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10247` | `adult_2_25 -> a2_25` | `s42` | retained as puffiness of face |
| `Id10248_a` + `Id10248_units=days` | `adult_2_26 -> a2_26a -> a2_26` | `s43` | retained as puffiness duration |
| `Id10248_b` + `Id10248_units=months` | `adult_2_26 -> a2_26b -> a2_26` | `s43` | retained as the same puffiness-duration feature after unit normalization |
| `Id10252` | `adult_2_27 -> a2_27` | `s44` | retained as general swelling of the body |
| visible WHO fields `Id10249`, `Id10250`, `Id10250_b`, `Id10251` | no explicit `who_data.py` or `who_prep.py` mapping from this visible WHO 2022 block | none from the visible swelling block | not visibly retained in the current adult WHO adapter |
| downstream adult variables `adult_2_29`, `adult_2_30`, `adult_2_31` | `a2_29`, `a2_30`, `a2_31` | `s46`, `s47`, `s48` | these belong to a different retained family and are fed by `Id10255`, `Id10256`, `Id10257`, not by the visible leg/feet-swelling block |
| `Id10476` contains swelling-related words | `adult_7_c -> a7_01` | `s999960` and related words | narrative word lane |

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10249` | Swollen legs or feet |
| `Id10250` | Duration of swelling lasted in days |
| `Id10250_b` | Duration of swelling lasted in months |
| `Id10251` | Both feet swollen |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| downstream child swelling family in the model | `child_4_36 -> c4_36`, `child_4_37 -> c4_37a/c4_37b -> c4_37` | `s145`, `s146` | the child SmartVA model has a swollen-legs-or-feet family |
| visible WHO fields `Id10249`, `Id10250`, `Id10250_b`, `Id10251` | no explicit `who_data.py` or `who_prep.py` mapping from this visible WHO 2022 block | none from the visible swelling block | not visibly wired from the displayed WHO block in this fork |
| `Id10476` narrative | `child_6_c -> c6_01` | `s999947` and related words | narrative word lane |

## Neonate

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| visible swelling block `Id10249` to `Id10251` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |
| neonatal skin/infection findings elsewhere | `c3_37+` family | broader neonatal skin and infection features | represented elsewhere rather than as a direct edema family |

## Current-State Takeaways

- adult puffiness of face and general body swelling are explicitly retained as `s42`, `s43`, and `s44`
- the visible leg/feet-swelling block `Id10249` to `Id10251` is not explicitly wired in the current WHO 2022 adapter for adult or child
- child and neonate do have broader downstream swelling-related variables in the model, but not through a visible one-to-one WHO 2022 mapping from this displayed block

This corrects the second-pass assumption that the visible leg/feet-swelling block was explicitly retained.

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Jaundice](jaundice.md)
