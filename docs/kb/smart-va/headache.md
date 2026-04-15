---
title: SmartVA Headache Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Headache

This document traces the WHO severe-headache question block around `Id10207` forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Stiff Neck](stiff-neck.md)
- [Mental Confusion](mental-confusion.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10207` | Severe headache |
| headache duration helper(s) | not surfaced as visible WHO 2022 mappings in this fork |
| headache onset helper(s) | not surfaced as visible WHO 2022 mappings in this fork |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| adult headache family in the downstream model | `adult_2_69 -> a2_69` | `s89` | the adult SmartVA model has a headache-present feature |
| adult headache duration family in the downstream model | `adult_2_70 -> a2_70a/a2_70b -> a2_70` | `s90` | the adult SmartVA model has a thresholded headache-duration feature |
| adult headache onset family in the downstream model | `adult_2_71 -> a2_71` | `s91` | the adult SmartVA model has a rapid-onset headache feature |
| visible WHO field `Id10207` | no explicit `who_data.py` or `who_prep.py` mapping to `adult_2_69`, `adult_2_70`, or `adult_2_71` in this fork | none from the visible WHO 2022 block | not visibly wired from the displayed WHO block |
| `Id10476` narrative | `adult_7_c -> a7_01` | no strong dedicated headache word feature identified | limited narrative role |

## Child

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10207` and nearby headache block | no child WHO-to-PHMRC mapping in the current adapter | none | ignored for child tariff scoring |

## Neonate

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10207` and nearby headache block | no neonate WHO-to-PHMRC mapping in the current adapter | none | ignored for neonate tariff scoring |

## Current-State Takeaways

- the adult SmartVA model includes a headache family: `s89`, `s90`, `s91`
- the visible WHO 2022 headache block does not show an explicit adapter path into that family in this fork
- child and neonate do not expose a direct headache family from this WHO block

So the downstream headache family is real, but it is not currently a visible WHO 2022 retained path in this codebase.
