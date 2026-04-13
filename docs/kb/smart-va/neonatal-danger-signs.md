---
title: SmartVA Neonatal Danger Signs Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Danger Signs

This document traces the neonatal danger-sign block `Id10284`, `Id10286`, `Id10287`, `Id10288`, and `Id10289` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Neonatal Unresponsive](neonatal-unresponsive.md)
- [Jaundice](jaundice.md)
- [Skin Other](skin-other.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10284` | Baby become cold to touch |
| `Id10286` | Baby become lethargic after a period of normal activity |
| `Id10287` | Baby have redness or pus oozing from the umbilical cord |
| `Id10288` | Baby have skin ulcer(s) or sore(s) |
| `Id10289` | Baby have yellow skin, palms or soles |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10284` | `child_3_29 -> c3_29` | `s90` | retained as `Cold to touch` |
| `Id10284` follow-up via `Id10285` | `child_3_30a -> c3_30a`, then `UNIT_IF_AMOUNT` fills `child_3_30 -> c3_30` | `s91` | transformed into `Started feeling cold to touch at least 3 days after birth` |
| `Id10286` | `child_3_32 -> c3_32` | `s93` | retained as `Became lethargic after a period of normal activity` |
| `Id10287` | `child_3_35 -> c3_35` | `s96` | retained as `Pus drainage from the umbilical cord stump` |
| `Id10288` | no explicit WHO-to-PHMRC mapping surfaced in this fork | none | not exposed as its own first-class tariff feature here |
| `Id10289` | `child_3_47 -> c3_47` | `s107` | retained as `Yellow skin` |

## Current-State Summary

This WHO block is only partly retained.

Retained directly:

- cold to touch: `s90`
- cold-start timing threshold: `s91`
- lethargic after normal activity: `s93`
- pus from umbilical cord stump: `s96`
- yellow skin: `s107`

Not surfaced as equally explicit retained tariff features in this fork:

- `Id10288` skin ulcers / sores

## Important Caveat

The cold-to-touch family is narrowed before tariff application:

- `Id10284` gives the main retained symptom `s90`
- the age-at-start follow-up is not kept raw
- it is thresholded through `child_3_30` into `s91`

So even when the WHO questionnaire captures timing detail, the SmartVA layer keeps only the thresholded version, not the original day count.
