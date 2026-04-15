---
title: SmartVA Neonatal Unresponsive Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
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
| `Id10281` | `child_3_33 -> c3_33` | `s94` | retained as `became unresponsive or unconscious` |
| downstream neonatal feature `child_3_34 -> c3_34` | `s95` | `s95` | downstream neonatal symptom exists, but no visible WHO 2022 mapping from `Id10282` or `Id10283` is surfaced in this fork |
| `Id10282` | no explicit mapping | none | not retained as its own first-class tariff feature |
| `Id10283` | no explicit mapping | none | not retained as its own first-class tariff feature |
| `Id10287` from a different neonatal danger-sign block | `child_3_35 -> c3_35` | `s96` | this is a different retained symptom (`pus drainage from the umbilical cord stump`), not the `Id10283` timing split |
| `Id10476` narrative | no strong dedicated neonatal unresponsive word lane identified | none | limited narrative role |

## Current-State Summary

The current neonatal unresponsive block keeps one direct structured signal:

- `Id10281 -> s94`

It does not keep the visible within-24-hours or more-than-24-hours split as explicit first-class inputs from `Id10282` or `Id10283`.

The important current-state clarification is that `child_3_35 -> s96` is not the retained path for `Id10283`. It comes from `Id10287`, a different neonatal danger-sign question entirely.
