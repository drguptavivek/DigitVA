---
title: SmartVA Abdominal Pain Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Abdominal Pain

This document traces the WHO abdominal-pain question block `Id10194` through `Id10199` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Vomiting](vomiting.md)
- [Urine Problems](urine-problems.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10194` | Abdominal pain |
| `Id10195` | Abdominal pain severe |
| `Id10196` | Duration of abdominal pain in hours |
| `Id10197` | Duration of abdominal pain in days |
| `Id10198` | Duration of abdominal pain in months |
| `Id10199` | Location of the abdominal pain |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10194` | `adult_2_61 -> a2_61` | `s80` | retained as belly pain |
| `Id10196` / `Id10197` / `Id10198` with `id10196_unit` | `adult_2_62 -> a2_62` | `s81` | transformed into thresholded duration |
| `Id10199` | `adult_2_63 -> a2_63_1` | `s82 -> s82991` | transformed into location-coded belly-pain feature, with lower-belly tariff split |
| `Id10476` contains abdomen terms | `adult_7_c -> a7_01` | `s99991` | generic narrative abdomen word lane |

### Adult Summary

The adult abdominal-pain family is retained as:

- `s80` belly pain
- `s81` abdominal-pain duration
- `s82` / `s82991` location-coded abdominal pain

Important current-state caveat:

`Id10195` severe abdominal pain does not appear as its own first-class tariff feature in the current adapter.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10194` through `Id10199` | abdominal-pain block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10194` through `Id10199` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |
| `Id10476` narrative | `child_6_c -> c6_01` | `s99991` | generic abdomen word lane only |

### Child Summary

The child pipeline does not expose a direct structured abdominal-pain family from this WHO block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10194` through `Id10199` | abdominal-pain block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10194` through `Id10199` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |
| neonatal narrative | `child_6_c -> c6_01` | `s99991` | generic abdomen word lane only |

### Neonate Summary

The neonate pipeline does not expose a direct structured abdominal-pain family from this WHO block.

## Current-State Takeaways

- adult abdominal pain: structured pain, duration, and location family plus a generic abdomen word lane
- child abdominal pain: this WHO block is not used structurally in the current tariff path
- neonate abdominal pain: this WHO block is not used structurally in the current tariff path
