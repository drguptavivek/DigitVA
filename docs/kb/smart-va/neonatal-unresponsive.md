---
title: SmartVA Neonatal Unresponsive Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Neonatal Unresponsive

This document traces the WHO neonatal unresponsive block `Id10281` through `Id10283` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Unconsciousness](unconsciousness.md)
- [Neonatal Physical Abnormality](neonatal-physical-abnormality.md)

## WHO Question Group

| WHO field | Label |
|---|---|
| `Id10281` | Baby become unresponsive or unconscious |
| `Id10282` | Baby become unresponsive or unconscious within 24 hours after birth |
| `Id10283` | Baby become unresponsive or unconscious more than 24 hours after birth |
| `Id10476` | Narration |

## Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10281` | `child_3_33 -> c3_33` | `s94` | retained as became unresponsive or unconscious |
| `Id10282` | no explicit WHO-to-PHMRC mapping in the current adapter | none | not exposed as its own first-class tariff feature |
| `Id10283` | no explicit WHO-to-PHMRC mapping in the current adapter | none | not exposed as its own first-class tariff feature |
| `Id10476` narrative | no strong dedicated neonatal unresponsive word lane identified | none | limited narrative role |

## Current-State Summary

The current neonatal unresponsive block keeps one direct structured signal:

- `Id10281 -> s94`

The within-24-hours and more-than-24-hours follow-up fields do not show equally explicit retained paths in this fork.

## Important Caveat

The downstream neonatal symptom model is clear that `s94` is a first-class retained feature. What is less explicit here is whether `Id10282` and `Id10283` are folded into other timing logic outside the visible WHO adapter lines or simply not retained as separate tariff-applied features. So the safe current-state reading is:

1. `Id10281` definitely survives directly
2. `Id10282` and `Id10283` do not show a clean explicit retained mapping here
3. the WHO block is narrowed before tariff application rather than preserved as a three-part structured family
