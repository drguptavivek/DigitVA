---
title: SmartVA Health Service HCW Cause Of Death Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Health Service HCW Cause Of Death

This document traces the `Health Service Utilisation / hcw_cod` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [Medical Certificates](medical-certs.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Id10435` | Health care worker tell you the cause of death |
| `Id10436` | Comment by health care worker |

## Forward Trace

### Adult

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10435` | `adult_6_3a -> a6_03` | none | retained only as an HCE-side metadata / gating field, not as a symptom variable |
| `Id10436` | `adult_6_3b -> a6_03b` | free-text word features | retained as free text and converted into word-derived SmartVA features when free-text processing is enabled |

### Child / Neonate

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10435` | `child_5_0a` | none | retained only as HCE-side metadata / gating, not as a symptom variable |
| `Id10436` | `child_5_0b -> c5_0b` | free-text word features | retained as free text and converted into word-derived features for child and neonate runs when free-text processing is enabled |

## Current-State Summary

This displayed subcategory contributes in two different ways:

- `Id10435` indicates that a health-care-worker COD statement exists, but it does not become a tariff symptom
- `Id10436` is treated as free-text clinical evidence and can generate open-response word features

So the comment field is the SmartVA-relevant part of this block.

## Important Caveat

The comment path is not a one-to-one question-to-symptom mapping.

`Id10436` enters the generic free-text pipeline, so its content may collapse into many possible word-derived SmartVA variables depending on the words present. It behaves more like the narrative text path than a normal yes/no symptom question.

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
- [Medical Certificates](medical-certs.md)
