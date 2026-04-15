---
title: SmartVA Health History Neonate Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Health History Neonate

This document traces the `Health History Details / neonate` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Duration Of Illness](duration-of-illness.md)
- [Neonatal Period General](neonatal-period-general.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10351` | Age of baby since fatal illness started |
| `Id10408` | The baby/the child grew normally before illness started |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10351` | `child_1_20a` together with helper duration-unit fields feeding `child_1_20 -> c1_20` | `s28` | retained as age-at-fatal-illness-started, but the actual downstream duration bucket depends on helper fields outside the displayed subcategory |
| `Id10408` | none | none | ignored before symptom and tariff stages |

## Current-State Summary

This subcategory contributes only one SmartVA-relevant concept in the current pipeline:

- age of the baby when the fatal illness started

What does not survive from the displayed block:

- the growth-normality question `Id10408`

## Important Caveat

The displayed subcategory is not self-contained.

`Id10351` alone does not define the full duration bucket used downstream. The prep path also depends on helper WHO fields such as `Id10352_a` and `Id10352_b`, which live outside this displayed subcategory.

So the safe current-state reading is:

1. `Id10351` is part of the retained age-at-onset path
2. the final downstream bucket is built with helper unit fields
3. `Id10408` does not participate in SmartVA scoring

## Code Map

- [Duration Of Illness](duration-of-illness.md)
- [Neonatal Period General](neonatal-period-general.md)
