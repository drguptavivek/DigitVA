---
title: SmartVA Smell Or Taste Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Smell Or Taste

This document traces the WHO smell-or-taste question `Id10486` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Headache](headache.md)
- [Mental Confusion](mental-confusion.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10486` | Experienced a new loss, change or decreased sense of smell or taste |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10486` | no adult WHO-to-PHMRC mapping in the current adapter | none | ignored before symptom and tariff stages |

### Adult Summary

`Id10486` does not currently feed a first-class adult SmartVA symptom.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10486` | smell / taste change |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10486` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored before symptom and tariff stages |

### Child Summary

`Id10486` does not currently feed a first-class child SmartVA symptom.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10486` | smell / taste change |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10486` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored before symptom and tariff stages |

### Neonate Summary

`Id10486` does not currently feed a first-class neonatal SmartVA symptom.

## Current-State Takeaways

- `Id10486` is currently ignored in the structured smart-va-pipeline
- there is no dedicated downstream smell-or-taste tariff feature for adult, child, or neonate
