---
title: SmartVA Stiff Neck Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Stiff Neck

This document traces the WHO stiff or painful neck question block `Id10208` and `Id10209*` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Convulsions](convulsions.md)
- [Unconsciousness](unconsciousness.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10208` | Stiff or painful neck? |
| `Id10209` | Duration of stiff or painful neck in days |
| `Id10209_b` | Duration of stiff or painful neck in months |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10208` | `adult_2_72 -> a2_72` | `s92` | retained as stiff neck |
| adult duration family in the downstream model | `adult_2_73 -> a2_73a/a2_73b -> a2_73` | `s93` | downstream stiff-neck duration feature exists |
| visible WHO fields `Id10209`, `Id10209_b` | no explicit `who_data.py` or `who_prep.py` mapping to `adult_2_73` in this fork | none from the visible WHO block | not visibly wired from the displayed WHO block |
| `Id10476` contains neck-related words | `adult_7_c -> a7_01` | `s9999113` and related words | weak narrative word lane |

## Child

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10208` | `child_4_28 -> c4_28` | `s136` | retained as stiff neck |
| `Id10476` narrative | `child_6_c -> c6_01` | `s999932` and related words | weak narrative word lane |

## Neonate

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10208` and `Id10209*` | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

## Current-State Takeaways

- adult stiff neck presence is explicitly retained: `Id10208 -> s92`
- adult stiff-neck duration `s93` exists downstream, but the visible WHO 2022 duration fields are not explicitly wired into it in this fork
- child stiff neck is explicitly retained: `Id10208 -> s136`
- neonate does not expose a direct stiff-neck family from this WHO block
