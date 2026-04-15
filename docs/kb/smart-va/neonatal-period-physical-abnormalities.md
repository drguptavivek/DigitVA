---
title: SmartVA Neonatal Period Physical Abnormalities Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Neonatal Period Physical Abnormalities

This document traces the `Neonatal Period Details / physical_abnormalities` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Neonatal Birth Condition](neonatal-birth-condition.md)
- [Neonatal Physical Abnormality](neonatal-physical-abnormality.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10370` | Any part of baby physically abnormal at time of delivery |
| `Id10371` | Swelling or defect on the back at time of birth |
| `Id10372` | Very large head at time of birth |
| `Id10373` | Very small head at time of birth |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10370` | `child_1_18 -> c1_18` | `s23` | retained on the stillbirth-side neonatal path as `physically abnormal at delivery` |
| `Id10371` | `child_1_19` multiselect -> `childabnorm3 -> c1_19_3` | `s26` | retained on the stillbirth-side neonatal path as `mass defect on back/head/spine` |
| `Id10372` | `child_1_19` multiselect -> `childabnorm2 -> c1_19_2` | `s25` | retained on the stillbirth-side neonatal path as `head size very large` |
| `Id10373` | `child_1_19` multiselect -> `childabnorm1 -> c1_19_1` | `s24` | retained on the stillbirth-side neonatal path as `head size very small` |
| `Id10370` | `child_3_2 -> c3_02` | `s61` | retained on the neonatal-illness path as `physically abnormal at delivery` |
| `Id10371` | `child_3_3` multiselect -> `childabnorm33 -> c3_03_3` | `s64` | retained on the neonatal-illness path as `mass defect on the back/head/spine` |
| `Id10372` | `child_3_3` multiselect -> `childabnorm32 -> c3_03_2` | `s63` | retained on the neonatal-illness path as `head size very large` |
| `Id10373` | `child_3_3` multiselect -> `childabnorm31 -> c3_03_1` | `s62` | retained on the neonatal-illness path as `head size very small` |

## Current-State Summary

This WHO block is retained twice in the current SmartVA path.

1. It feeds the `child_1_*` stillbirth-side neonatal variables.
2. It also feeds the `child_3_*` neonatal-illness variables.

So the same four WHO questions are not collapsed to one single abnormality flag. They are preserved as a small abnormality family in two parallel neonatal branches.

## What Is Retained

Stillbirth-side neonatal branch:

- `Id10370 -> s23`
- `Id10373 -> s24`
- `Id10372 -> s25`
- `Id10371 -> s26`

Neonatal-illness branch:

- `Id10370 -> s61`
- `Id10373 -> s62`
- `Id10372 -> s63`
- `Id10371 -> s64`

## Important Caveat

This document is about the `Neonatal Period Details / physical_abnormalities` subcategory with `Id10370` through `Id10373`.

It is different from [Neonatal Physical Abnormality](neonatal-physical-abnormality.md), which covers the later neonatal-feeding block `Id10277` through `Id10279`.

## Code Map

- [Neonatal Birth Condition](neonatal-birth-condition.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
