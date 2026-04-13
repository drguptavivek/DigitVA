---
title: SmartVA Neonatal Birth Weight Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Birth Weight

This document traces the neonatal birth-weight block `Id10363`, `Id10365`, and `Id10366` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Period General](neonatal-period-general.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10363` | Baby weighing under 2.5 kg at birth |
| `Id10365` | Baby weighing over 4.5 kg at birth |
| `Id10366` | Weight (in grammes) of the deceased at birth |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10363` | `map_child_birth_size_2022()` builds `child_1_7 -> c1_07 -> s13_1` | `s13` | transformed into the small-at-birth binary feature |
| `Id10365` | `map_child_birth_size_2022()` builds `child_1_7 -> c1_07 -> s13_1` | none | contributes to the birth-size category, but does not create its own tariff-applied large-baby feature |
| `Id10366` | `child_1_8a -> c1_08b` plus `UNIT_IF_AMOUNT` fills `child_1_8 -> c1_08a` | `s14` | transformed into the birth-weight threshold feature |

## Current-State Summary

The current neonatal birth-weight path narrows WHO weight inputs into two SmartVA ideas:

1. small or very small at birth: `s13`
2. birth weight at least 2500 grams: `s14`

What is not retained:

- the raw gram value from `Id10366`
- a distinct high-birth-weight tariff feature for `Id10365`

So this block is thresholded rather than preserved as raw measurement detail.

## Important Caveat

The birth-size categorization is not a direct one-to-one field map. It is created in `who_prep.py` by `map_child_birth_size_2022()`, which compresses the WHO birth-size questions into the PHMRC-style `child_1_7` category before symptom conversion.
