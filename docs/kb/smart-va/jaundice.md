---
title: SmartVA Jaundice Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Jaundice

This document traces the WHO yellow-discoloration and jaundice-like question family forward through the current `smart-va-pipeline`.

Related docs:

- [SmartVA Symptom KB](README.md)
- [Swelling](swelling.md)
- [Fever](fever.md)

## Adult

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10265` | Yellow discoloration of the eyes |
| duration field(s) for yellow discoloration | Duration of yellow discoloration |
| `Id10267` | Hair change to reddish / yellowish color |
| `Id10477:Jaundice` | Narration keyword: Jaundice |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10265` | `adult_2_21 -> a2_21` | `s38` | retained as yellow discoloration of the eyes |
| duration field(s) | intended `adult_2_22 -> a2_22` | `s39` | separate duration feature when present |
| `Id10267` | `adult_2_31 -> a2_31` | `s48` | related but separate yellowing/hair-change feature |
| `Id10476` contains jaundice-related words | `adult_7_c -> a7_01` | `s999997` and related words | narrative word lane |
| `Id10477:Jaundice` | `adult_7_6 -> a_7_6` | jaundice word feature | collapses into the narrative word lane for jaundice-related words |

### Adult Summary

Adult jaundice is partly structured and partly word-driven. The main retained structured feature is `s38`, while keyword and narrative references converge through word features.

## Child

### WHO Question Group

| WHO field | Label |
|---|---|
| yellow-discoloration path in child questionnaire | Yellow discoloration / pallor-related signs |
| `Id10267` | Hair changed color |
| `Id10478:jaundice` | Narration keyword: jaundice |
| `Id10476` | Narration |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| yellowing-related signs | child skin / nutrition paths | child yellow/pallor features such as `s148` and `s150`-adjacent family | represented through related child signs rather than one direct jaundice feature |
| `Id10267` | `child_4_39 -> c4_39` | `s148` | separate yellowing-related sign |
| `Id10476` narrative | `child_6_c -> c6_01` | `s999949` and related words | narrative word lane |
| `Id10478:jaundice` | `child_6_8 -> c_6_8` | `s999949` | collapses into the same word lane as narrative jaundice |

### Child Summary

Child jaundice is more word-driven than adult jaundice in the current pipeline.

## Neonate

### WHO Question Group

| WHO field | Label |
|---|---|
| `Id10289` | Yellow skin, palms or soles |
| eye-yellowing follow-up | Yellow eyes |
| `Id10476` | Narration |
| `Id10479` | Neonatal narration keywords |

### Forward Trace

| WHO source | PHMRC-style variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| yellow-skin question | `c3_47` | `s107` | retained as yellow skin |
| yellow-eyes question | `c3_48` | `s108` | retained as yellow eyes |
| `Id10476` narrative | `child_6_c -> c6_01` | no dedicated neonatal jaundice word collapse identified | weak narrative role |
| `Id10479` keywords | `neonate_6_*` | no jaundice keyword exists | no neonatal jaundice keyword lane |

### Neonate Summary

Neonate jaundice is a direct structured family: `s107` and `s108`.

## Current-State Takeaways

- adult jaundice: one main structured feature plus a word lane
- child jaundice: largely represented through related signs and word features
- neonate jaundice: direct structured yellow-skin / yellow-eyes family

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
