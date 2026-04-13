---
title: SmartVA Vomiting Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Vomiting

This document traces the WHO vomiting question block `Id10188` through `Id10192` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Abdominal Pain](abdominal-pain.md)
- [Diarrhea](diarrhea.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10188` | Vomit |
| `Id10189` | Vomitted the week preceding the death |
| `Id10189_1` | Vomitted every time when ate or drank |
| `Id10190_a` | Duration of vomit in days |
| `Id10190_b` | Duration of vomit in months |
| `Id10191` | Blood in the vomit |
| `Id10192` | Black colored vomit |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10189` | `adult_2_53 -> a2_53` | `s72` | retained as vomitted in the week preceding death |
| duration detail | downstream `adult_2_54 -> a2_54` family | `s73` | separate duration feature exists downstream |
| `Id10191` | `adult_2_55 -> a2_55` | `s74` | retained as blood in the vomit |
| `Id10192` | `adult_2_56 -> a2_56` | `s75` | retained as black vomit |
| `Id10476` contains vomit terms | `adult_7_c -> a7_01` | `s9999166` | narrative vomit word lane |

### Adult Summary

The current adult vomiting family is tariff-active through:

- `s72` recent vomiting
- `s73` vomiting duration
- `s74` blood in the vomit
- `s75` black vomit

Important current-state caveat:

The downstream adult symptom family is clear, but the WHO adapter does not show a clean direct structured use of every visible WHO vomiting question. In particular, `Id10188` and `Id10189_1` are not exposed as obvious first-class tariff features in the current adapter.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10188` through `Id10192` | vomiting block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10188` through `Id10192` | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |
| `Id10476` narrative | `child_6_c -> c6_01` | `s999948` and related words | narrative vomit word lane only |

### Child Summary

The child pipeline does not expose a direct structured vomiting family from this WHO block. Only a weaker narrative vomit word lane is visible.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| neonatal vomiting family | neonatal feeding / vomiting block |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| neonatal vomiting question | `c3_11 -> s72` and nearby neonatal feeding/vomiting family | neonatal-specific symptom variables | represented through a separate neonatal symptom family, not through the adult WHO block |

### Neonate Summary

The neonate pipeline has vomiting-related symptoms, but not through the adult WHO `Id10188` through `Id10192` block.

## Current-State Takeaways

- adult vomiting: compact structured family plus a narrative vomit word lane
- child vomiting: no direct structured family from this WHO block; only a weaker narrative lane
- neonate vomiting: represented in a separate neonatal symptom family
