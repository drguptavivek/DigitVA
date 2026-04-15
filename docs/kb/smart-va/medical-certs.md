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

## Forward Trace

### Adult

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10464` | `adult_6_11 -> a6_11` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10466` | `adult_6_12 -> a6_12` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10468` | `adult_6_13 -> a6_13` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10470` | `adult_6_14 -> a6_14` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10472` | `adult_6_15 -> a6_15` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10462`, `Id10463`, `Id10465`, `Id10467`, `Id10469`, `Id10471`, `Id10473` | no adult symptom-stage mapping | none | not retained as first-class adult SmartVA features |

### Child / Neonate

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10462` | `child_5_10 -> c5_10` | none | visible in prep variables, but no downstream symptom-stage retention is visible in this fork |
| `Id10464` | `child_5_12 -> c5_12` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10466` | `child_5_13 -> c5_13` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10468` | `child_5_14 -> c5_14` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10470` | `child_5_15 -> c5_15` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10472` | `child_5_16 -> c5_16` | free-text word features | retained as certificate cause text and converted through the generic free-text word path |
| `Id10463`, `Id10465`, `Id10467`, `Id10469`, `Id10471`, `Id10473` | no child/neonate symptom-stage mapping | none | not retained as first-class child or neonate SmartVA features |

## Current-State Summary

This displayed subcategory splits into two very different behaviors.

What matters for SmartVA scoring:

- certificate cause-text fields `Id10464`, `Id10466`, `Id10468`, `Id10470`, `Id10472`
- those fields enter generic free-text word extraction, not direct structured symptom mapping

What does not become a first-class SmartVA feature:

- sharing / issuance flags
- all certificate duration fields
- `Id10462` as a downstream symptom variable

## Important Caveat

The certificate text fields do not map one-to-one to a named symptom.

They behave like auxiliary narrative inputs. Words from those certificate fields can generate many different open-response SmartVA variables depending on the text present.

So the current pipeline uses medical certificates as additional free-text evidence, not as a separate structured certificate model.

## Code Map

- [Health Service HCW Cause Of Death](health-service-hcw-cod.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
