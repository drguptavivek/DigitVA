---
title: SmartVA Uncategorized And System Fields
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# Uncategorized And System Fields

This document closes the pass over the `Uncategorized Or System Fields` section in [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md).

These fields are present in `mas_field_display_config` but are not assigned to a user-facing category/subcategory block. They still matter because some are helper inputs to the `smart-va-pipeline`, while others are runtime metadata that never reach SmartVA scoring.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Duration Of Illness](duration-of-illness.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)

## Helper And System Groups

| Field or field group | Role | Current SmartVA status |
|---|---|---|
| `age_adult`, `age_child_days`, `age_child_months`, `age_child_unit`, `age_child_years`, `ageInDaysNeonate`, `ageInMonthsByYear`, `ageInMonthsRemain`, `ageInYearsRemain`, `isAdult1`, `isAdult2`, `isChild1`, `isChild2`, `isNeonatal1`, `isNeonatal2` | age derivation helpers | consumed by `who_prep.calculate_age()` or related age routing logic; they support `gen_5_4*` age variables rather than becoming symptoms themselves |
| `finalAgeInYears` | DigitVA prep fallback | used in DigitVA `va_smartva_02_prepdata.py` to synthesize `ageInDays` when raw day-age is blank |
| `Id10120_0`, `Id10120_1`, `id10120_unit` | illness-duration helpers | used by child/neonate illness-duration prep; `Id10120_1` is the important prepared day value that feeds `s29` |
| `Id10148_b`, `Id10148_units`, `Id10154_a`, `Id10154_units` | child fever/cough duration helpers | used by WHO-to-PHMRC duration conversion for child symptom families |
| `Id10161_1`, `id10161_unit`, `Id10167_b`, `Id10167_units`, `Id10178_unit`, `Id10182_a`, `Id10182_units`, `Id10184_units`, `Id10190_units`, `id10196_unit`, `Id10197_a`, `Id10201_a`, `Id10201_unit`, `Id10205_a`, `Id10205_unit`, `Id10209_a`, `Id10209_units`, `Id10213_b`, `Id10213_units`, `Id10216_a`, `Id10216_units`, `Id10232_a`, `Id10232_units`, `Id10248_a`, `Id10248_units`, `Id10250_a`, `Id10250_units`, `Id10262_a`, `Id10262_units`, `Id10266_a`, `Id10266_units`, `Id10274_a`, `Id10274_b`, `Id10274_units` | adult/neonate duration helper fields | support duration-unit normalization and thresholding for the linked visible WHO symptom families; they are helper inputs, not standalone symptoms |
| `survey_block`, `telephonic_consent` | non-standard form metadata | explicitly dropped before SmartVA input is written |
| `md_available`, `md_count`, `ds_available`, `ds_count` | attachment counters / availability flags | retained in payload and workflow context, but not used by SmartVA mapping or scoring |
| `audit`, `deviceid`, `start`, `today`, `confirm_inst` | submission/runtime metadata | not used by SmartVA scoring; `start` matters elsewhere in DigitVA preprocessing but not for symptom mapping |
| `Id10020`, `Id10022`, `Id10023_a`, `Id10023_b`, `Id10051`, `Id10069_a`, `Id10071_check`, `Id10073`, `Id10077_b`, `Id10253`, `Id10313` | uncategorized questionnaire one-offs | no direct current WHO-to-PHMRC mapping was surfaced in this pass; treat as non-scoring unless a future deeper trace proves otherwise |

## Current-State Summary

The uncategorized/system fields fall into four buckets:

1. true helper inputs that support age or duration conversion
2. DigitVA runtime metadata that never becomes SmartVA signal
3. non-standard columns intentionally dropped before `smartva_input.csv`
4. uncategorized one-off fields with no visible current SmartVA mapping

The most important helper fields are:

- age derivation fields
- the prepared day field `Id10120_1`
- the many `*_a`, `*_b`, and `*_units` duration helpers referenced by already-traced symptom families

## Important Caveat

Not every uncategorized field was traced into a unique named function in this pass.

For many duration helpers, the current-state conclusion is pattern-based and source-backed:

- the visible symptom doc shows the downstream family
- `who_data.py` shows the related helper/unit fields
- the helper field is therefore part of the conversion path even if it is not documented as a standalone symptom input

So this document should be read as a helper/system-field closure pass, not as a new symptom-family pass.

## Code Map

- [Duration Of Illness](duration-of-illness.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)
