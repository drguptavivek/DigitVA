---
title: SmartVA Diarrhea Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Diarrhea

This document traces the WHO diarrhea question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Fever](fever.md)
- [Cough](cough.md)
- [Breathing Difficulty](breathing-difficulty.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10181` | Diarrhoea |
| duration field(s) for diarrhoea | Duration of diarrhoea |
| `Id10186` | Blood in stools |
| narrative text containing diarrhea-related words | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10181` | `adult_2_47 -> a2_47` | `s66` | retained as frequent loose or liquid stools |
| duration field(s) | intended `adult_2_48 -> a2_48` | `s67` | treated as a separate duration feature when present |
| bowel-habit change field(s) | `adult_2_49 -> a2_49` | `s68` | separate bowel-habit feature |
| `Id10186` | `adult_2_50 -> a2_50` | `s69` | retained as blood in stool |
| stool-blood continuation field(s) | `adult_2_51 -> a2_51` | `s70` | continuation-to-death feature |
| narrative text | `adult_7_c -> a7_01` | `s999953` and related words | narrative word lane |

### Adult Summary

Adult diarrhea is modeled as a structured family, not one single feature.

Main downstream features are:

- `s66` diarrhea
- `s67` diarrhea duration
- `s68` bowel-habit change
- `s69` blood in stool
- `s70` blood in stool up until death

Narrative text adds a separate word lane.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10181` | Diarrhoea |
| `Id10182_b / Id10182` | Duration of diarrhoea |
| `Id10183` | Number of stools |
| `Id10185` | Diarrhoea continued until death |
| `Id10186` | Blood in stools |
| `Id10476` | Narration |
| `Id10478:diarrhea` | Narration keyword: diarrhea |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10181` | `child_4_6 -> c4_06` | `s115` | retained as loose or liquid stools |
| `Id10183` | `child_4_7 -> c4_07` | `s116` | stool-frequency feature |
| duration field(s) | `child_4_8 / child_4_8a -> c4_08` | `s117` | diarrhea-duration feature |
| `Id10185` | `child_4_9 -> c4_09` | `s118` | continued until death |
| stop-timing field(s) | `child_4_10 / child_4_10a -> c4_10` | `s119` | stopped-before-death feature |
| `Id10186` | `child_4_11 -> c4_11` | `s120` | blood in stool |
| `Id10476` contains diarrhea words | `child_6_c -> c6_01` | `s999916` | narrative word lane |
| `Id10478:diarrhea` | `child_6_5 -> c_6_5` | `s999916` | collapses into the same word lane as narrative diarrhea |

### Child Summary

Child diarrhea has a richer structured family than adult diarrhea and also has a collapsed narrative/keyword word lane.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| neonatal loose-stools question feeding `c3_44` | Frequent loose or liquid stools |
| follow-on stool-frequency question feeding `c3_45` | More than one loose stool |
| `Id10476` | Narration |
| `Id10479` | Neonatal narration keywords |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| loose-stools question | `c3_44` | `s104` | retained as neonatal loose stools |
| stool-frequency follow-up | `c3_45` | `s105` | retained as more-than-one-loose-stool feature |
| `Id10476` narrative | `child_6_c -> c6_01` | no neonatal diarrhea word feature seen | no neonatal diarrhea word lane identified |
| `Id10479` keywords | `neonate_6_* -> n_6_*` | no diarrhea keyword exists | no neonatal diarrhea keyword lane |

### Neonate Summary

Neonate diarrhea is present as a small structured family and does not currently show the same narrative/keyword collapse pattern seen in child fever or child diarrhea.

## Current-State Takeaways

- adult diarrhea: structured family plus separate narrative word lane
- child diarrhea: structured family plus collapsed narrative/keyword word lane
- neonate diarrhea: small structured family only

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
