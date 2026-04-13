---
title: SmartVA Mass Abdomen Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Mass Abdomen

This document traces the WHO mass-in-the-abdomen question block `Id10204` through `Id10206` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Protruding Abdomen](protruding-abdomen.md)
- [Abdominal Pain](abdominal-pain.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10204` | Mass in the abdomen |
| `Id10205` | Duration of mass in the abdomen in days |
| `Id10206` | Duration of mass in the abdomen in months |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10204` | `adult_2_67 -> a2_67` | `s87` | retained as mass in the belly |
| `Id10205` / `Id10206` with `Id10205_unit` | `adult_2_68 -> a2_68` | `s88` | transformed into thresholded duration |
| `Id10476` contains abdomen terms | `adult_7_c -> a7_01` | `s99991` | generic narrative abdomen word lane |

### Adult Summary

The adult mass-abdomen family is retained as one direct structured finding plus a duration feature.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10204` through `Id10206` | mass-abdomen block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10204` through `Id10206` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline does not expose a direct mass-abdomen family from this WHO block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10204` through `Id10206` | mass-abdomen block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10204` through `Id10206` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not expose a direct mass-abdomen family from this WHO block.

## Current-State Takeaways

- adult mass abdomen: structured presence and duration family plus a generic abdomen word lane
- child mass abdomen: this WHO block is not used in the current tariff path
- neonate mass abdomen: this WHO block is not used in the current tariff path
