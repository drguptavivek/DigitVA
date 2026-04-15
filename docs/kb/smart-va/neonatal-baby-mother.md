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
| `Id10399` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications1 -> c2_01_1` | `s33` | retained as maternal convulsions complication |
| `Id10396` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications2 -> c2_01_2` | `s34` | retained as maternal hypertension complication |
| `Id10401` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications3 -> c2_01_3` | `s35` | retained as maternal severe-anemia complication |
| `Id10397` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications4 -> c2_01_4` | `s36` | retained as maternal diabetes complication |
| `Id10402` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications8 -> c2_01_8` | `s40` | retained as vaginal-bleeding complication |
| `Id10395` | `REVERSE_ONE_HOT_MULTISELECT -> child_2_1 -> complications9 -> c2_01_9` | `s41` | retained as maternal fever-during-labour complication |
| `Id10391`, `Id10393`, `Id10398`, `Id10400` | no visible WHO-to-PHMRC mapping from this displayed block | none | not retained from this displayed subcategory |
| downstream neonatal vaccination feature | `child_2_11 -> c2_11` | `s54` | exists in the neonate model, but the visible vaccination fields are not mapped into it in this fork |

## Cross-Subcategory Complication Merge

The retained `child_2_1` complication family is built from multiple subcategories.

This `baby_mother` block contributes:

- `Id10399`
- `Id10396`
- `Id10401`
- `Id10397`
- `Id10402`
- `Id10395`

The separate neonatal delivery block also contributes to the same family through:

- `Id10403`
- `Id10405`
- `Id10404`

So the current retained complication family is a deliberate cross-subcategory merge, not a one-subcategory-only structure.

## Current-State Summary

What this subcategory clearly contributes:

- maternal convulsions
- maternal hypertension
- maternal severe anemia
- maternal diabetes
- maternal vaginal bleeding
- maternal fever during labour

What it does not currently contribute as visible retained WHO 2022 inputs:

- vaccination fields `Id10391` and `Id10393`
- foul-smelling vaginal discharge `Id10398`
- blurred vision `Id10400`

The earlier `cross-subcategory merge` note is now explicit and complete.

## Code Map

- [Neonatal Delivery](neonatal-delivery.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
