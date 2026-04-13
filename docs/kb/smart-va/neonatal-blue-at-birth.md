---
title: SmartVA Neonatal Blue At Birth Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Blue At Birth

This document traces the WHO field `Id10406` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Danger Signs](neonatal-danger-signs.md)
- [Neonatal Birth Condition](neonatal-birth-condition.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10406` | Baby blue in colour at birth |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10406` | no explicit WHO-to-PHMRC mapping surfaced in this fork | none | not exposed as its own first-class SmartVA feature in the visible adapter |

## Current-State Summary

`Id10406` is visible in the WHO questionnaire labels, but I do not see a matching explicit retained path into the neonatal SmartVA symptom layer in this fork.

So the safe current-state reading is:

1. the WHO field exists
2. no direct `who_data.py` line is visible for it
3. no first-class tariff-applied feature can be attributed to it with confidence here

## Important Caveat

This is a documentation-of-current-behavior page, not a correctness judgment. The absence of an explicit retained path means only that the visible adapter does not expose `Id10406` as a first-class SmartVA feature here.
