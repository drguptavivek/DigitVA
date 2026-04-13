---
title: SmartVA Neonatal Birth Condition Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Birth Condition

This document traces the neonatal birth-condition block `Id10109` through `Id10116` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Cry](neonatal-cry.md)
- [Neonatal Fetal Movement](neonatal-fetal-movement.md)
- [Neonatal Physical Abnormality](neonatal-physical-abnormality.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10109` | Baby ever move after being delivery |
| `Id10110` | Baby ever breathe |
| `Id10111` | Baby breathe immediately after birth |
| `Id10112` | Baby had breathing problem |
| `Id10113` | Baby was given assistance to breathe at birth |
| `Id10114` | Baby born dead |
| `Id10115` | Bruises / Injury on baby's body after the birth |
| `Id10116` | Baby's body was soft, discoloured and the skin peeling away |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10109` | `child_1_13 -> c1_13` | `s18` | retained as `Baby did move` |
| `Id10110` | `child_1_14 -> c1_14` | `s19` | retained as `Baby did breathe` |
| `Id10111` | `child_3_4 -> c3_04` | `s65` | retained as `Breathed immediately after birth` |
| `Id10112` | `child_3_5 -> c3_05` | `s66` | retained as `Difficulty breathing` |
| `Id10113` | `child_3_6 -> c3_06` | `s67` | retained as `Something was done to try to help the baby breathe at birth` |
| `Id10114` | `child_1_11 -> c1_11 -> s16_1` | `s16` | transformed into `Baby was born dead` |
| `Id10115` | `child_1_16 -> c1_16` | `s21` | retained as `Bruises or signs of injury on body at birth` |
| `Id10116` | `child_1_17 -> c1_17` | `s22` | retained as `Body (skin and tissue) pulpy` |

## Current-State Summary

This neonatal block is mostly retained as first-class tariff features.

The main retained signals are:

- movement after delivery: `s18`
- ever breathed: `s19`
- breathed immediately after birth: `s65`
- breathing difficulty: `s66`
- breathing assistance at birth: `s67`
- born dead: `s16`
- birth injury / bruising: `s21`
- macerated or pulpy body: `s22`

So the current pipeline keeps this birth-condition family much more explicitly than many later neonatal follow-up blocks.

## Important Caveat

`Id10114` does not remain as a raw categorical field. It is recoded through `child_1_11`, and only the `dead` branch survives into tariff-applied `s16`.
