---
title: SmartVA Demographic General Trace
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-13
---

# Demographic General

This document traces the `Demographic Details / general` subcategory from `WHO_2022_VA_SOCIAL` forward through the current `smart-va-pipeline`.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Risk Factors](risk-factors.md)
- [SmartVA Analysis](../../current-state/smartva-analysis.md)

## WHO Subcategory Fields

| WHO field | Label |
|---|---|
| `Site` | Site |
| `unique_id` | Unique ID |
| `site_individual_id` | Deceased's site ID |
| `Id10017` | Name |
| `Id10018` | Surname |
| `Id10021` | Birth date |
| `Id10023` | Death date |
| `Id10024` | Year of death |
| `isNeonatal` | The deceased person is a Neonate |
| `isChild` | The deceased person is a Child |
| `isAdult` | The deceased person is an Adult |
| `ageInDays` | Age (in days) |
| `ageInDays2` | Age (in days) |
| `ageInYears` | Age (in years) |
| `ageInMonths` | Age (in months, post last birthday) |
| `age_group` | Age group |
| `age_neonate_days` | Age of neonate in days |
| `age_neonate_hours` | Age of neonate in hours |
| `ageInYears2` | Age (in years) |
| `Id10019` | Sex |
| `survey_state` | Survey state |
| `survey_district` | Survey district |
| `Id10002` | Region of high HIV/AIDS mortality? |
| `Id10003` | Region of high malaria mortality? |
| `Id10004` | Season of death |
| `Id10058` | Place of death |
| `Id10052` | Citizenship/nationality |
| `Id10053` | Ethnicity |
| `Id10054` | Place of birth |
| `Id10055` | Usual residence |
| `Id10057` | Place of death (country, province, district, village) |
| `Id10059` | Marital status |
| `Id10063` | Highest level of schooling |
| `Id10064` | Able to read and/or write |
| `Id10065` | Economic activity status in year prior to death |
| `Id10066` | Occupation |
| `Id10061` | Father name |
| `Id10062` | Mother name |

## Forward Trace

| WHO source | PHMRC-style / prep variable | Symptom-stage / tariff-applied feature | Current behavior |
|---|---|---|---|
| `Id10019` | `gen_5_2 -> g5_02` | `real_gender -> sex` | retained as sex across adult, child, and neonate |
| `ageInYears`, `ageInYears2`, `ageInMonths`, `ageInDays`, `age_neonate_days` and related derived age fields | `who_prep.calculate_age()` populates `gen_5_4`, `gen_5_4a`, `gen_5_4b`, `gen_5_4c`, `agedays` | age features differ by age group | retained as the age backbone for SmartVA routing and tariff conditioning |
| `isAdult`, `isChild`, `isNeonatal` | fallback into `gen_5_4d` when no usable numeric age is available | module routing fallback only | used for age-group fallback, not as tariff features themselves |
| `ageInYears` family on adult rows | `gen_5_4a -> g5_04a` | `real_age -> age` | adult keeps age in years as the tariff age variable |
| `ageInYears` and `ageInMonths` / `ageInDays` on child rows | `gen_5_4a/b/c -> g5_04a/b/c` | `real_age -> age`, plus `s3` and `s4` | child retains age in years and also keeps month/day-derived child-age features |
| `age_neonate_days` / day-level age fields on neonate rows | `gen_5_4c -> g5_04c` | `age` | neonate uses day-level age directly as the tariff age variable |
| `Site`, `unique_id`, `site_individual_id` | none | none | ignored before SmartVA scoring |
| `Id10017`, `Id10018`, `Id10021`, `Id10023`, `Id10024` | none | none | ignored before SmartVA scoring |
| `survey_state`, `survey_district`, `Id10002`, `Id10003`, `Id10004`, `Id10052` to `Id10066` | none | none | ignored before SmartVA scoring |

## Adult Summary

Adult SmartVA keeps two demographic controls from this subcategory:

- `sex`
- `age`

They are not symptom questions, but they are still tariff-active because the adult cause restrictions and some scoring behavior depend on age and sex.

The age path is:

1. DigitVA-derived age fields such as `ageInYears` or `ageInDays`
2. `who_prep.calculate_age()` fills `gen_5_4*`
3. adult pre-symptom renames `gen_5_4a -> g5_04a`
4. adult symptom prep converts `g5_04a -> real_age -> age`

The sex path is:

1. `Id10019`
2. `gen_5_2`
3. `g5_02`
4. `real_gender -> sex`

## Child Summary

Child SmartVA also keeps `sex` and `age`, but it preserves more child-age detail than the adult path.

Current child behavior uses:

- `g5_04a -> real_age -> age`
- `g5_04b -> s3`
- `g5_04c -> s4`

So this subcategory is part of child routing and also produces child age features beyond one simple age value.

## Neonate Summary

Neonate SmartVA relies most heavily on day-level age from this subcategory.

Current neonate behavior uses:

- `g5_04c -> age`
- `g5_04b -> s3`
- `g5_02 -> sex`

So for neonates, the derived day-age fields are operationally important to the SmartVA path.

## Current-State Takeaways

- Most of this subcategory is metadata and does not reach SmartVA.
- The fields that matter are the sex field plus the derived age and age-group fields.
- `isAdult`, `isChild`, and `isNeonatal` are fallback routing helpers when numeric age is missing.
- Adult, child, and neonate all use the same high-level demographic source block, but they retain different downstream age features.

## Code Map

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [Field Mapping System](../../current-state/field-mapping-system.md)
