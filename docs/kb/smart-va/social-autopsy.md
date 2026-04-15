---
title: SmartVA Social Autopsy Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Social Autopsy

This document traces the `Social Autopsy / Social Autopsy` category from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Social Autopsy Analysis Policy](../../policy/social-autopsy-analysis.md)

## WHO Subcategory Fields

This category contains the social-autopsy questionnaire fields, including:

- `sa01` through `sa19`
- `sa06_a`, `sa05_a`, `sa07_a`
- `sa_tu13` through `sa_tu19`

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `sa01` to `sa19`, `sa_*`, `sa_tu*` | none | none | explicitly dropped in DigitVA prep before SmartVA input is written |

## Current-State Summary

The social-autopsy questionnaire is not part of SmartVA scoring.

In DigitVA's SmartVA prep step, social-autopsy fields are removed before the SmartVA input CSV is generated. So they do not feed:

- WHO-to-PHMRC mapping
- free-text word extraction
- symptom-stage variables
- tariff-applied features

## Important Caveat

This category still matters in DigitVA, but through a separate path.

There are two different things here:

1. mapped ODK social-autopsy fields, which are dropped before SmartVA
2. the app-owned Social Autopsy analysis workflow used in coding, which is separate from SmartVA and controlled by project settings

So the safe current-state reading is:

- social-autopsy content exists in DigitVA
- it is intentionally excluded from SmartVA processing
- it has its own separate coding and policy path

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Social Autopsy Analysis Policy](../../policy/social-autopsy-analysis.md)
