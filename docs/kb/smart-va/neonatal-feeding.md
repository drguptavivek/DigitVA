---
title: SmartVA Neonatal Feeding Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Neonatal Feeding

This document traces the `Neonatal Feeding Symptoms / feeding` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Neonatal Unresponsive](neonatal-unresponsive.md)
- [Neonatal Danger Signs](neonatal-danger-signs.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10271` | Baby able to suckle or bottle-feed within the first 24 hours after birth |
| `Id10272` | Baby ever suckle in a normal way |
| `Id10273` | Baby stop suckling |
| `Id10274_c` | Duration after birth when the baby stop suckling (in months) |
| `Id10274` | Duration after birth when the baby stop suckling (in days) |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10271` | `child_3_11 -> c3_11` | `s72` | retained as normal suckling during the first day of life |
| `Id10272` | `child_3_12 -> c3_12` | `s73` | retained as ever suckled normally |
| `Id10273` | `child_3_13 -> c3_13` | `s74` | retained as stopped suckling normally |
| `Id10274`, `Id10274_c` plus duration helper fields | `child_3_14 -> c3_14` | `s75` | retained as stop-suckling timing, then thresholded into a neonatal tariff duration feature |

## Current-State Summary

This displayed subcategory is cleanly retained in the neonate path.

What survives:

- first-day suckling `s72`
- ever suckled normally `s73`
- stopped suckling `s74`
- stopped-suckling timing `s75`

This subcategory does not contribute to adult or child SmartVA scoring.

## Important Caveat

The duration line for `Id10274` is not driven only by the visible day or month field.

Like other WHO duration questions, the prep path uses helper duration-unit fields from the uncategorized bucket to build the final `child_3_14 -> c3_14 -> s75` value.

So the safe current-state reading is:

1. the neonatal feeding family is retained end to end
2. the duration part is transformed into a threshold feature
3. helper duration fields still matter even though they are not shown in this subcategory

## Code Map

- [Neonatal Unresponsive](neonatal-unresponsive.md)
- [Neonatal Danger Signs](neonatal-danger-signs.md)
