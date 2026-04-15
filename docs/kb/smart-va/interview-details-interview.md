---
title: SmartVA Interview Details Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Interview Details

This document traces the `Interview Details / interview` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Demographic General](demographic-general.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `language` | Interview language |
| `Id10012` | Date of the VA interview |
| `Id10013` | Consent acquired for VA interview |
| `Id10011` | Start time of the interview |
| `Id10481` | Submission finalised as of |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10013` | `gen_3_1 -> g3_01` | none | retained as the consent header used by `CommonPrep` to reject refused-consent records before scoring |
| `Id10012` | `interviewdate` | output metadata only | retained for SmartVA output formatting, not for symptom or tariff scoring |
| `language` | none from payload | none | ignored by the SmartVA data path; output language comes from the run option, not this field |
| `Id10011` | none | none | ignored before scoring |
| `Id10481` | none | none | ignored before scoring |

## Current-State Summary

This subcategory is operational, not clinical.

What matters in the current SmartVA path:

- `Id10013` controls whether the record is processed at all
- `Id10012` can appear in output metadata

What does not become SmartVA symptom or tariff data:

- interview language
- interview start time
- submission finalised timestamp

## Important Caveat

The `language` field shown in the form does not control the SmartVA output language. The SmartVA CLI uses a separate run option such as `--language english`.

So this WHO subcategory should be understood as:

1. consent gating
2. output metadata
3. not a symptom block

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Field Mapping System](../../current-state/field-mapping-system.md)
