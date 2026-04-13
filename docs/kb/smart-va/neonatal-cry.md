---
title: SmartVA Neonatal Cry Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Cry

This document traces the WHO neonatal cry block `Id10104` through `Id10107` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Birth Condition](neonatal-birth-condition.md)
- [Neonatal Unresponsive](neonatal-unresponsive.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10104` | Baby ever cried |
| `Id10105` | Baby cried immediately after birth |
| `Id10106` | Minutes after birth the baby first cried |
| `Id10107` | Baby stop being able to cry |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10104` | `child_1_12 -> c1_12` | `s17` | retained as `Baby did cry` |
| `Id10105` | `child_3_7 -> c3_07` | `s68` | retained as `Cried immediately after birth` |
| `Id10105` + `Id10106` | `map_neonate_first_cry()` builds `child_3_8 -> c3_08` | `s69 -> s69991` | transformed into delayed-or-never-first-cry logic |
| `Id10107` | `child_3_9 -> c3_09` | `s70` | retained as `Stopped being able to cry` |

## Current-State Summary

The current neonatal cry path keeps three distinct ideas:

1. whether the baby ever cried at all: `s17`
2. whether the baby cried immediately after birth: `s68`
3. whether the first cry was delayed or never happened: `s69991`
4. whether the baby later stopped being able to cry: `s70`

The important narrowing happens in `map_neonate_first_cry()`:

- `Id10106` is not kept as raw minutes
- it is bucketed into `child_3_8`
- only the delayed / never categories survive as tariff-applied `s69991`

So this block is not reduced to one single cry variable, but the timing detail is compressed before tariff application.

## Important Caveat

`Id10105` participates in two downstream paths:

1. directly into `s68`
2. indirectly into the derived `child_3_8` timing bucket when `Id10106` is missing

That means the same WHO question contributes both a direct immediate-cry signal and a fallback delayed-or-never-first-cry derivation.
