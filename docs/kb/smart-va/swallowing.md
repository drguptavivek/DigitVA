---
title: SmartVA Swallowing Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Swallowing

This document traces the WHO swallowing difficulty question block `Id10261` through `Id10264` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Abdominal Pain](abdominal-pain.md)
- [Chest Pain](chest-pain.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10261` | Difficulty or pain in swallowing |
| `Id10262` | Duration of difficulty or pain in swallowing in days |
| `Id10262_b` | Duration of difficulty or pain in swallowing in months |
| `Id10262_c` | Swallowing become impossible |
| `Id10263` | Swallowing solids / liquids / both |
| `Id10264` | Pain upon swallowing |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10261` | `adult_2_57 -> a2_57` | `s76` | retained as difficulty swallowing |
| `Id10262` / `Id10262_b` with `Id10262_units` | `adult_2_58 -> a2_58` | `s77` | transformed into thresholded duration |
| `Id10263` | `adult_2_59 -> a2_59` | `s78` | transformed into solids / liquids / both, with tariff-active emphasis on `both` |
| `Id10264` | `adult_2_60 -> a2_60` | `s79` | retained as pain upon swallowing |
| `Id10476` narrative | `adult_7_c -> a7_01` | no strong dedicated swallowing word feature identified | limited narrative role |

### Adult Summary

The adult swallowing family is one of the cleaner structured mappings in the current pipeline:

- `s76` difficulty swallowing
- `s77` duration of difficulty swallowing
- `s78` both solids and liquids
- `s79` pain upon swallowing

Important current-state caveat:

The WHO adapter also contains a legacy combined-question conversion around `Id10261`, so the swallowing block is partly shaped by backward-compatibility logic rather than one perfectly clean WHO-to-PHMRC mapping.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10261` through `Id10264` | swallowing block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10261` through `Id10264` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

### Child Summary

The child pipeline does not expose a direct swallowing-difficulty family from this WHO block.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10261` through `Id10264` | swallowing block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10261` through `Id10264` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

### Neonate Summary

The neonate pipeline does not expose a direct swallowing family from this WHO block.

## Current-State Takeaways

- adult swallowing: structured four-part family
- child swallowing: this WHO block is not used in the current tariff path
- neonate swallowing: this WHO block is not used in the current tariff path
- adult swallowing is retained as separate downstream signals rather than collapsed into one single tariff variable
