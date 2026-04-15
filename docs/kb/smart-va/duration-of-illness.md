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

## Forward Trace

### Adult

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| illness-duration inputs from this WHO block | `adult_2_1` with unit/value split through `adult_2_1a` to `adult_2_1d` -> `a2_01a/a2_01b -> a2_01` | `s15` | retained as adult illness duration and thresholded at 30 days |
| `Id10123` | no explicit adult WHO override for sudden death in this block | none | no separate adult sudden-death feature is visible from this WHO block |

### Child

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10120` days, using the WHO-calculated day field `Id10120_1` | `who_prep.map_child_illness_duration() -> child_1_21a`, with `child_1_21 = 4` | `c1_21 -> s29` | retained as child illness duration |
| `Id10121` months | `who_prep.map_child_illness_duration() -> child_1_21b`, with `child_1_21 = 2` | `c1_21 -> s29` | retained as child illness duration |
| `Id10122` years | `who_prep.map_child_illness_duration() -> child_1_21c`, then normalized into the month branch with `child_1_21 = 2` | `c1_21 -> s29` | retained as child illness duration after year-to-month conversion |
| `Id10123` | `child_3_49 -> c3_49` exists in WHO 2022 overrides, but no child symptom-stage retention is visible | none | no first-class child sudden-death feature is retained in the child tariff path |

### Neonate

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10120` days, using the WHO-calculated day field `Id10120_1` | `who_prep.map_child_illness_duration() -> child_1_21a`, with `child_1_21 = 4` | `c1_21 -> s29` | retained as neonate illness duration |
| `Id10121` months | `who_prep.map_child_illness_duration() -> child_1_21b`, with `child_1_21 = 2` | `c1_21 -> s29` | retained as neonate illness duration |
| `Id10122` years | `who_prep.map_child_illness_duration() -> child_1_21c`, then normalized into the month branch with `child_1_21 = 2` | `c1_21 -> s29` | retained as neonate illness duration after year-to-month conversion |
| `Id10123` | `child_3_49 -> c3_49` | `s109` | retained on the neonate path as `appeared healthy and then just die suddenly` |

## Current-State Summary

Adult, child, and neonate do not use this block in the same way.

- adult keeps one illness-duration feature: `s15`
- child keeps one illness-duration feature: `s29`
- neonate keeps one illness-duration feature: `s29`, plus a separate sudden-death feature `s109`

So `Id10123` is not just another duration input. In the current WHO 2022 override path, it becomes neonate-only sudden-death signal.

## Thresholding

- adult: `s15` means illness longer than 30 days
- child: `s29` means illness lasted at least 8 days
- neonate: `s29` means illness lasted at least 3 days

## Important Caveat

The child and neonate duration mapper explicitly reads `Id10120_1`, not the visible UI field `Id10120` directly. That means the smart-va-pipeline is relying on the WHO-prepared day value rather than the raw display field alone.

For adult duration, the downstream path is clear, but the WHO-side builder for `adult_2_1` is less explicit in this fork than the child/neonate helper in `who_prep.py`.

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Demographic General](demographic-general.md)
