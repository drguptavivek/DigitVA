---
title: SmartVA Duration Of Illness Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Duration Of Illness

This document traces the `General Symptoms / duration_of_illness` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Demographic General](demographic-general.md)
- [Neonatal Period General](neonatal-period-general.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10123` | Deceased died suddenly |
| `Id10121` | Duration of illness in months before death |
| `Id10122` | Duration of illness in years before death |
| `Id10120` | Duration of illness in days before death |
| `Id10120_1` | WHO-prepared helper day value used by the child/neonate mapper |

## Forward Trace

### Adult

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| adult illness-duration family in the downstream model | `adult_2_1 -> a2_01a/a2_01b -> a2_01` | `s15` | the adult SmartVA model has this duration feature |
| visible WHO fields `Id10120`, `Id10121`, `Id10122` | no explicit `who_data.py` or `who_prep.py` mapping to `adult_2_1` in this fork | none from the visible WHO 2022 block | not explicitly wired from the displayed WHO block |
| `Id10123` | no adult WHO 2022 override for sudden death | none | no separate adult sudden-death feature is exposed from this block |

### Child

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10120_1` | `who_prep.map_child_illness_duration() -> child_1_21a`, with `child_1_21 = 4` | `c1_21 -> s29` | retained as child illness duration |
| `Id10121` | `who_prep.map_child_illness_duration() -> child_1_21b`, with `child_1_21 = 2` | `c1_21 -> s29` | retained as child illness duration |
| `Id10122` | `who_prep.map_child_illness_duration() -> child_1_21c`, then normalized into the month branch with `child_1_21 = 2` | `c1_21 -> s29` | retained as child illness duration after year-to-month conversion |
| `Id10123` | `child_3_49 -> c3_49` exists in the downstream child/neonate model | none on the child tariff path | not retained as a first-class child symptom |

### Neonate

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10120_1` | `who_prep.map_child_illness_duration() -> child_1_21a`, with `child_1_21 = 4` | `c1_21 -> s29` | retained as neonate illness duration |
| `Id10121` | `who_prep.map_child_illness_duration() -> child_1_21b`, with `child_1_21 = 2` | `c1_21 -> s29` | retained as neonate illness duration |
| `Id10122` | `who_prep.map_child_illness_duration() -> child_1_21c`, then normalized into the month branch with `child_1_21 = 2` | `c1_21 -> s29` | retained as neonate illness duration after year-to-month conversion |
| `Id10123` | `child_3_49 -> c3_49` | `s109` | retained on the neonate path as `appeared healthy and then just die suddenly` |

## Current-State Summary

The visible WHO duration block is explicit for child and neonate, but not for adult.

- adult: the downstream SmartVA model has `s15`, but this fork does not expose a visible WHO 2022 mapping from `Id10120` to `Id10122` into `adult_2_1`
- child: `Id10120_1`, `Id10121`, and `Id10122` are explicitly normalized into `s29`
- neonate: the same duration helper path feeds `s29`, and `Id10123` additionally feeds `s109`

So the current adult WHO 2022 adapter is materially less explicit here than the child and neonate path.

## Thresholding

- adult model: `s15` means illness longer than 30 days
- child: `s29` means illness lasted at least 8 days
- neonate: `s29` means illness lasted at least 3 days

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Demographic General](demographic-general.md)
