---
title: SmartVA Neonatal Period General Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Period General

This document traces the WHO neonatal period general block `Id10354` and `Id10367` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Physical Abnormality](neonatal-physical-abnormality.md)
- [Neonatal Unresponsive](neonatal-unresponsive.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10354` | Child part of a multiple birth |
| `Id10367` | Duration of pregnancy before the child was born in months |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10354` | no explicit WHO-to-PHMRC mapping line visible in this fork | none from this exact WHO field | not exposed as a clean first-class retained line here |
| `Id10367` | no explicit WHO-to-PHMRC mapping line visible in this fork | none from this exact WHO field | not exposed as a clean first-class retained line here |

## Related Downstream Neonatal Concepts

Even though the exact WHO adapter lines for `Id10354` and `Id10367` are not visible here, the downstream neonatal symptom and tariff model does contain related concepts:

| Downstream concept | Symptom / tariff feature | Current behavior |
|---|---|---|
| part of multiple birth | `s5` | first-class neonatal tariff feature exists downstream |
| pregnancy duration at least threshold | `s45` | first-class neonatal tariff feature exists downstream |
| pregnancy ended early / late | `s46991` / `s46992` | transformed gestational-duration split exists downstream |

## Current-State Summary

The safe current-state reading is:

1. the neonatal tariff model definitely has multiple-birth and gestational-duration concepts
2. this fork does not show clean explicit WHO adapter lines from `Id10354` and `Id10367` into those downstream variables
3. so these exact WHO fields should be treated as adapter-unclear rather than directly traceable in the same way as cleaner symptom blocks

## Important Caveat

This is a good example of the difference between:

- a downstream SmartVA concept clearly existing, and
- the exact WHO 2022 field feeding it being explicit in the adapter code.

For `Id10354` and `Id10367`, the first is visible and the second is not.
