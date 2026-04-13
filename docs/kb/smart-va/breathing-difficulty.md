---
title: SmartVA Breathing Difficulty Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Breathing Difficulty

This document traces the WHO breathing-difficulty and related respiratory question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Cough](cough.md)
- [Fever](fever.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10159` | Difficulty breathing / breathlessness |
| duration field(s) for breathing difficulty | Duration of breathing difficulty |
| `Id10165` | Breathing difficulty continuous or on and off |
| `Id10170` | Unable to carry out daily routines due to breathlessness |
| `Id10171` | Breathless while lying flat |
| `Id10166` | Fast breathing |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10159` | `adult_2_36 -> a2_36` | `s53` | retained as difficulty breathing |
| duration field(s) | intended `adult_2_37 -> a2_37` | `s54` | treated as a separate duration feature when present |
| `Id10165` | `adult_2_38 -> a2_38` | `s55 -> s55991 / s55992` | transformed into continuous vs on-and-off bins |
| position / orthopnea field(s) | `adult_2_39 -> a2_39` | `s56 -> s56991 / s56992 / s56993 / s56994` | transformed into positional-worsening bins |
| `Id10166` | `adult_2_40 -> a2_40` | `s58` | retained as fast breathing |
| fast-breathing duration field(s) | `adult_2_41 -> a2_41` | `s59` | retained as separate duration feature |
| wheeze / related respiratory sign | `adult_2_42 -> a2_42` | `s60` | separate respiratory feature |
| `Id10476` narrative contains respiratory words | `adult_7_c -> a7_01` | word features such as `s999958` | narrative word lane |

### Adult Summary

Adult breathlessness is modeled as a family of structured respiratory features plus a narrative word lane.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10159` | Difficulty breathing |
| duration field(s) for breathing difficulty | Duration of breathing difficulty |
| `Id10166` | Fast breathing |
| duration field(s) for fast breathing | Duration of fast breathing |
| `Id10172` | Chest in-drawing |
| `Id10173_nc` | Breathing sounded like |
| `Id10173_a` | Wheezing |
| `Id10476` | Narration |
| `Id10478:pneumonia` | Narration keyword: pneumonia |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10159` | `child_4_16 -> c4_16` | `s125` | retained as difficulty breathing |
| duration field(s) | `child_4_17 / child_4_17a -> c4_17` | `s126` | retained as difficulty-breathing duration |
| `Id10166` | `child_4_18 -> c4_18` | `s127` | retained as fast breathing |
| fast-breathing duration field(s) | `child_4_19 / child_4_19a -> c4_19` | `s128` | retained as fast-breathing duration |
| `Id10172` | `child_4_20 -> c4_20` | `s129` | retained as chest in-drawing |
| `Id10173_nc` | `child_4_23 -> c4_23` | `s131` | transformed into breathing-sound feature |
| `Id10173_a` / wheeze path | `child_4_24 -> c4_24` | `s132` | retained as wheezing |
| `Id10476` narrative | `child_6_c -> c6_01` | respiratory word features such as `s999938` | narrative word lane |
| `Id10478:pneumonia` | `child_6_9 -> c_6_9` | pneumonia-related word feature | keyword lane for a related respiratory concept |

### Child Summary

Child respiratory features are more granular than adult:

- breathing difficulty
- fast breathing
- chest in-drawing
- breathing-sound features such as grunting or wheezing

Narrative text adds a separate respiratory word lane.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10159`-mapped neonatal breathing path | Difficulty breathing |
| neonatal timing field(s) for breathing difficulty | When breathing difficulty started |
| neonatal duration field(s) for breathing difficulty | Duration of breathing difficulty |
| neonatal fast-breathing fields | Fast breathing |
| neonatal grunting / chest indrawing fields | Respiratory distress signs |
| `Id10476` | Narration |
| `Id10479` | Neonatal narration keywords |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| breathing-difficulty question | `c3_17` | `s78` | retained as neonatal difficulty breathing |
| timing field | `c3_18` | `s79` | difficulty-breathing timing feature |
| duration field | `c3_19` | `s80` | duration feature |
| fast-breathing question | `c3_20` | `s81` | retained as neonatal fast breathing |
| fast-breathing timing field | `c3_21` | `s82` | timing feature |
| fast-breathing duration field | `c3_22` | `s83` | duration feature |
| chest in-drawing / grunting | `c3_23 / c3_24` | `s84 / s85` | retained as respiratory distress signs |
| `Id10476` narrative | `child_6_c -> c6_01` | respiratory word features such as `s999931` | narrative word lane |
| `Id10479` keywords | `neonate_6_3 / neonate_6_4 / neonate_6_6` | lung/pneumonia/respiratory-distress word features | keyword lane for respiratory concepts |

### Neonate Summary

Neonate respiratory modeling is the richest of the three groups. It includes direct difficulty breathing, fast breathing, timing, duration, and distress-sign features.

## Current-State Takeaways

- adult breathing difficulty: structured family plus narrative word lane
- child breathing difficulty: structured family plus respiratory narrative/keyword lanes for related concepts
- neonate breathing difficulty: dense structured family plus respiratory narrative/keyword lanes

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
