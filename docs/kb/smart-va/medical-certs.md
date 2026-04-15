---
title: SmartVA Medical Certificates Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Medical Certificates

This document traces the `Narration / Documents / medical_certs` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Health Service HCW Cause Of Death](health-service-hcw-cod.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10462` | Medical certificate of cause of death issued |
| `Id10463` | Shared medical certificate of cause of death with VA interviewer |
| `Id10464` | Immediate cause of death from the cause of death certificate |
| `Id10465` | Duration of the immediate cause of death |
| `Id10466` | First antecedent cause of death from the cause of death certificate |
| `Id10467` | Duration of the first antecedent cause of death |
| `Id10468` | Second antecedent cause of death from the cause of death certificate |
| `Id10469` | Duration of second antecedent cause of death |
| `Id10470` | Third antecedent cause of death from the cause of death certificate |
| `Id10471` | Duration of third antecedent cause of death |
| `Id10472` | Contributing cause(s) of death from the cause of death certificate |
| `Id10473` | Duration of the contributing cause(s) of death |

## Adult Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10464` | `RENAME_QUESTIONS -> adult_6_11 -> a6_11` | free-text-derived word features | retained through the generic free-text branch |
| `Id10466` | `RENAME_QUESTIONS -> adult_6_12 -> a6_12` | free-text-derived word features | retained through the generic free-text branch |
| `Id10468` | `RENAME_QUESTIONS -> adult_6_13 -> a6_13` | free-text-derived word features | retained through the generic free-text branch |
| `Id10470` | `RENAME_QUESTIONS -> adult_6_14 -> a6_14` | free-text-derived word features | retained through the generic free-text branch |
| `Id10472` | `RENAME_QUESTIONS -> adult_6_15 -> a6_15` | free-text-derived word features | retained through the generic free-text branch |
| `Id10462`, `Id10463`, `Id10465`, `Id10467`, `Id10469`, `Id10471`, `Id10473` | no adult symptom-stage conversion | none | not retained as first-class adult SmartVA features |

## Child / Neonate Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10462` | `RENAME_QUESTIONS -> child_5_10 -> c5_10` | none | present as a prep variable, but there is no child/neonate symptom-stage conversion from it |
| `Id10464` | `RENAME_QUESTIONS -> child_5_12 -> c5_12` | free-text-derived word features | retained through the generic free-text branch |
| `Id10466` | `RENAME_QUESTIONS -> child_5_13 -> c5_13` | free-text-derived word features | retained through the generic free-text branch |
| `Id10468` | `RENAME_QUESTIONS -> child_5_14 -> c5_14` | free-text-derived word features | retained through the generic free-text branch |
| `Id10470` | `RENAME_QUESTIONS -> child_5_15 -> c5_15` | free-text-derived word features | retained through the generic free-text branch |
| `Id10472` | `RENAME_QUESTIONS -> child_5_16 -> c5_16` | free-text-derived word features | retained through the generic free-text branch |
| `Id10463`, `Id10465`, `Id10467`, `Id10469`, `Id10471`, `Id10473` | no child/neonate symptom-stage mapping | none | not retained as first-class child or neonate features |

## Free-Text Handling Path

The retained certificate text fields are not mapped to named structured symptoms.

They follow the generic free-text path instead:

1. `who_data.py` renames the certificate text fields into `adult_6_11` to `adult_6_15` or `child_5_12` to `child_5_16`
2. `common_data.py` includes those variables in `FREE_TEXT_VARS`
3. `pre_symptom_prep.py` runs `convert_free_text_vars()`
4. text is tokenized, stemmed, and matched through `WORDS_TO_VARS`
5. the output is a set of open-response SmartVA word features such as `s9999...`

## Current-State Summary

This subcategory splits into two different behaviors.

Retained:

- certificate cause-text fields `Id10464`, `Id10466`, `Id10468`, `Id10470`, `Id10472`
- these are retained only as generic free-text evidence

Not retained as first-class structured inputs:

- issuance and sharing flags
- all certificate duration fields
- `Id10462` as a symptom-stage feature

So the medical certificate block is now fully characterized as an auxiliary free-text source, not a structured SmartVA submodel.

## Code Map

- [Health Service HCW Cause Of Death](health-service-hcw-cod.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
