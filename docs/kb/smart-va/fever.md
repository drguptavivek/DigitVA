---
title: SmartVA Fever Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Fever

This document traces the WHO fever question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Cough](cough.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10147` | Fever |
| `Id10148*` | Duration of fever |
| `Id10150` | Severity of the fever |
| `Id10151` | Pattern of the fever |
| `Id10476` | Narration |
| `Id10477:Fever` | Narration keyword: Fever |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10147` | `adult_2_2 -> a2_02` | `s16` | retained as structured fever |
| `Id10148*` | intended `adult_2_3 / adult_2_3a -> a2_03` | `s17` | treated as a separate fever-duration feature when present |
| `Id10150` | `adult_2_4 -> a2_04` | `s18 -> s18991 / s18992` | transformed into severity bins |
| `Id10151` | `adult_2_5 -> a2_05` | `s19 -> s19991 / s19992` | transformed into pattern bins |
| `Id10476` contains `fever` | `adult_7_c -> a7_01` | `s999969` | narrative word lane |
| `Id10477:Fever` | `adult_7_3 -> a_7_3` | `s999969` | collapses into the same word lane as narrative fever |

### Adult Summary

Current adult behavior has two fever lanes:

1. structured fever lane
   `s16`, `s17`, `s18991`, `s18992`, `s19991`, `s19992`
2. word lane
   `s999969`

So adult fever is not reduced to one single SmartVA variable.

What collapses:

- `Id10476` narrative mention of fever
- `Id10477:Fever` keyword selection

Both converge to `s999969`.

What stays separate:

- fever presence
- fever duration
- fever severity
- fever pattern

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10147` | Fever |
| `Id10148_b / Id10148_c` | Duration of fever |
| `Id10150` | Severity of the fever |
| `Id10476` | Narration |
| `Id10478:fever` | Narration keyword: fever |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10147` | `child_4_1 -> c4_01` | `s110` | retained as structured fever |
| `Id10148_b / Id10148_c` | `child_4_2 / child_4_2a -> c4_02` | `s111` | retained as separate fever-duration feature |
| `Id10150` | `child_4_4 -> c4_04` | `s113 -> s113991` | transformed / bucketed |
| `Id10476` contains `fever` | `child_6_c -> c6_01` | `s999919` | narrative word lane |
| `Id10478:fever` | `child_6_6 -> c_6_6` | `s999919` | collapses into the same word lane as narrative fever |

### Child Summary

Child fever behaves like adult fever in structure:

- structured fever remains separate from narrative/keyword word features
- narrative fever and keyword fever collapse together into one downstream word feature

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| neonatal fever question feeding `c3_26` | Fever |
| neonatal fever timing question feeding `c3_27` | Age when fever started |
| neonatal fever duration question feeding `c3_28` | Duration of fever |
| `Id10476` | Narration |
| `Id10479` | Neonatal narration keywords |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| fever question | `c3_26` | `s87` | retained as neonatal fever |
| fever start timing question | `c3_27` | `s88` | retained as a separate timing feature |
| fever duration question | `c3_28` | `s89` | retained as a separate duration feature |
| `Id10476` narrative | `child_6_c -> c6_01` | no fever word feature seen | no neonatal fever narrative collapse identified |
| `Id10479` keywords | `neonate_6_* -> n_6_*` | no fever keyword exists | no neonatal fever keyword lane |

### Neonate Summary

Neonatal fever is currently a structured symptom family:

- `s87`
- `s88`
- `s89`

Unlike adult and child, there is no clear neonatal fever word lane in the current pipeline.

## Current-State Takeaways

- adult fever: split structured family plus a collapsed narrative/keyword word lane
- child fever: split structured family plus a collapsed narrative/keyword word lane
- neonate fever: structured family only

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
