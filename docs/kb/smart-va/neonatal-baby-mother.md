---
title: SmartVA Neonatal Baby Mother Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Neonatal Baby Mother

This document traces the `Neonatal Period Details / baby_mother` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Neonatal Delivery](neonatal-delivery.md)
- [Neonatal Period General](neonatal-period-general.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10391` | Mother received any vaccinations since reaching adulthood including during this pregnancy |
| `Id10393` | Mother received tetanus toxoid (TT) vaccine |
| `Id10395` | Mother had fever during labour |
| `Id10396` | Mother had high blood pressure during last 3 months of pregnancy, labour or delivery |
| `Id10397` | Mother had diabetes mellitus |
| `Id10398` | Mother had foul smelling vaginal discharge during pregnancy or after delivery |
| `Id10399` | Mother had convulsions during last 3 months of pregnancy, labour or delivery |
| `Id10400` | Mother had blurred vision during last 3 months of pregnancy |
| `Id10401` | Mother had severe anemia |
| `Id10402` | Mother had vaginal bleeding during last 3 months of pregnancy but before labour started |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10399` | `child_2_1 -> complications1 -> c2_01_1` | `s33` | retained as maternal convulsions complication |
| `Id10396` | `child_2_1 -> complications2 -> c2_01_2` | `s34` | retained as maternal hypertension complication |
| `Id10401` | `child_2_1 -> complications3 -> c2_01_3` | `s35` | retained as maternal severe-anemia complication |
| `Id10397` | `child_2_1 -> complications4 -> c2_01_4` | `s36` | retained as maternal diabetes complication |
| `Id10402` | `child_2_1 -> complications8 -> c2_01_8` | `s40` | retained as vaginal-bleeding complication |
| `Id10395` | `child_2_1 -> complications9 -> c2_01_9` | `s41` | retained as maternal fever-during-labour complication |
| `Id10391` | no visible WHO-to-PHMRC mapping from this field | none | not retained from this displayed subcategory |
| `Id10393` | no visible WHO-to-PHMRC mapping from this field | none | not retained from this displayed subcategory |
| `Id10398` | no visible WHO-to-PHMRC mapping from this field | none | not retained from this displayed subcategory |
| `Id10400` | no visible WHO-to-PHMRC mapping from this field | none | not retained from this displayed subcategory |

## Cross-Subcategory Complication Merge

The complication family fed by `child_2_1` does not come only from this displayed subcategory.

The same downstream complication multiselect also includes delivery-side WHO fields:

- `Id10403`
- `Id10405`
- `Id10404`

Those live in the `Neonatal Period Details / delivery` subcategory, but they are merged into the same downstream `c2_01_*` complication family.

So the current pipeline is not a one-to-one trace from the visible `baby_mother` UI block.

## Current-State Summary

What this subcategory clearly contributes:

- maternal convulsions
- maternal hypertension
- maternal severe anemia
- maternal diabetes
- maternal vaginal bleeding
- maternal fever during labour

What it does not clearly contribute in this fork:

- adult-life vaccination field `Id10391`
- tetanus toxoid field `Id10393`
- foul-smelling vaginal discharge field `Id10398`
- blurred vision field `Id10400`

## Important Caveat

There is a downstream neonatal vaccination feature `s54`, but in the current WHO adapter it is not fed from `Id10391` or `Id10393` in a visible one-to-one way here.

So the safe current-state reading is:

1. the displayed WHO subcategory is only partly retained
2. the retained part is folded into the neonatal complications family
3. that complications family also pulls fields from the delivery subcategory

## Code Map

- [Neonatal Delivery](neonatal-delivery.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
