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

## Helper Fields Used By The Pipeline

| WHO helper field | Role |
|---|---|
| `Id10352_a` | month-side helper for `child_1_20` |
| `Id10352_b` | day-side helper for `child_1_20` |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10351` | `RENAME_QUESTIONS -> child_1_20a` | helper only | visible onset-age value retained as one part of the onset-age family |
| `Id10352_a` | `RENAME_QUESTIONS -> child_1_20b` | helper only | month-side helper retained |
| `Id10352_b` | `RENAME_QUESTIONS -> child_1_20c` | helper only | day-side helper retained |
| `Id10352_a` / `Id10352_b` | `UNIT_IF_AMOUNT -> child_1_20`, then `child_pre_symptom_data.RECODE_MAP -> c1_20` | `s28` | explicit helper-driven path to age-at-fatal-illness-started |
| `Id10408` | none | none | ignored before symptom and tariff stages |

## Current-State Summary

This subcategory contributes one retained SmartVA concept:

- age of the baby when the fatal illness started

The key current-state detail is that the visible field `Id10351` is not sufficient by itself. The final retained path is built as:

1. `Id10351 -> child_1_20a`
2. helper fields `Id10352_a` and `Id10352_b` define the unit path
3. `child_1_20 -> c1_20`
4. `c1_20 -> s28`

So the earlier helper-dependency note is now explicit rather than partial.

`Id10408` does not participate in SmartVA scoring.

## Code Map

- [Duration Of Illness](duration-of-illness.md)
- [Neonatal Period General](neonatal-period-general.md)
