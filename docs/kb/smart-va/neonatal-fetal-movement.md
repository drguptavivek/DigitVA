---
title: SmartVA Neonatal Fetal Movement Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Fetal Movement

This document traces the fetal-movement block `Id10376` and `Id10377` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Birth Condition](neonatal-birth-condition.md)
- [Neonatal Delivery](neonatal-delivery.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10376` | Baby stop moving in womb before or after the onset of labour |
| `Id10377` | Baby stop moving in the womb |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10377` | `child_2_4 -> c2_04` | `s47` | retained as `Moved in the last few days before the birth` |
| `Id10376` | no explicit WHO-to-PHMRC mapping surfaced in this fork | none | not exposed as its own first-class tariff feature |

## Current-State Summary

The current pipeline keeps one direct fetal-movement signal here:

- `Id10377 -> s47`

The timing follow-up `Id10376` does not show a matching direct retained path in the visible adapter tables.

## Important Caveat

This block is one of the places where the WHO questionnaire is richer than the retained SmartVA symptom layer. The current safe reading is:

1. loss or change of movement before birth is represented by `s47`
2. the before-versus-after-onset-of-labour distinction from `Id10376` is not preserved as a separate tariff-applied feature in this fork
