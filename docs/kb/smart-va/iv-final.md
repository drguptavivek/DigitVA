---
title: SmartVA Interviewer Final Comment Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Interviewer Final Comment

This document traces the `Narration / Documents / iv_final` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `comment` | Final comment / any remarks by VA interviewer |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `comment` | no direct WHO-to-PHMRC mapping | none | ignored by the current SmartVA adapter and not included in SmartVA free-text processing |

## Current-State Summary

The interviewer final comment is not part of the current SmartVA evidence path.

It does not feed:

- structured SmartVA variables
- generic free-text word extraction
- tariff-applied symptoms

## Important Caveat

This field is not treated the same way as:

- `Id10476` narrative text
- `Id10436` health-worker COD comment
- `Id10464` and similar medical-certificate cause text fields

Those fields are wired into SmartVA free-text handling. `comment` is not.

## Code Map

- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)
