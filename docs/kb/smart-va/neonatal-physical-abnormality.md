---
title: SmartVA Neonatal Physical Abnormality Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Physical Abnormality

This document traces the WHO neonatal physical-abnormality block `Id10277` through `Id10279` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Convulsions](convulsions.md)
- [Unconsciousness](unconsciousness.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10277` | Baby's body become stiff, with the back arched backwards |
| `Id10278` | Baby have a bulging or raised fontanelle |
| `Id10279` | Baby have a sunken fontanelle |
| `Id10476` | Narration |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10278` | `child_4_29 -> c4_29` | `s137` | retained as bulging fontanelle |
| `Id10277` | no explicit WHO-to-PHMRC mapping in the current adapter | none | ignored before symptom and tariff stages |
| `Id10279` | no explicit WHO-to-PHMRC mapping in the current adapter | none | ignored before symptom and tariff stages |
| `Id10476` narrative | no strong dedicated physical-abnormality word lane identified | none | limited narrative role |

## Current-State Summary

The current pipeline keeps only one direct first-class signal from this WHO block:

- `Id10278 -> s137` for bulging fontanelle

What does not currently show a clean direct retained path in this fork:

- `Id10277` body become stiff, with back arched backwards
- `Id10279` sunken fontanelle

## Important Caveat

Even though this WHO block sits under neonatal physical abnormalities, the retained explicit downstream path visible in this fork runs through the `child_4_29 -> c4_29 -> s137` line rather than through a separately named neonatal-specific adapter variable. So the safe current-state reading is:

1. bulging fontanelle definitely survives as a direct SmartVA feature
2. the other two fields in this WHO block do not show an equally explicit retained path here
3. the pipeline is selective rather than preserving the whole WHO block as a single neonatal physical-abnormality family
