---
title: WHO 2022 Age Derivation Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-23
---

# WHO 2022 Age Derivation Policy

## Purpose

This document defines the policy baseline for interpreting WHO 2022 VA age fields in DigitVA.

It applies to:

- sync-time storage of raw ODK WHO 2022 age fields
- dashboard and analytics logic
- materialized views and reporting datasets
- SmartVA and human-coding comparison outputs that need age bands

## Source Form Logic

The WHO 2022 XLSForm has two parallel age derivation paths.

### Date-derived path

When date of birth and date of death are available, the form derives:

- `ageInDays`
- `ageInYears`
- `ageInYearsRemain`
- `ageInMonths`
- `ageInMonthsRemain`

This path is the more detailed age calculation path.

### Manual age-group path

When exact dates are unavailable or incomplete, the form captures age through age-group-specific inputs:

- `age_group`
- `age_neonate_days`
- `age_neonate_hours`
- `age_child_unit`
- `age_child_days`
- `age_child_months`
- `age_child_years`
- `age_adult`

From those manual inputs, the form derives:

- `ageInMonthsByYear`
- `ageInYears2`

### Final coarse age field

The form derives `finalAgeInYears` as:

- `ageInYears` when the date-derived path is available
- otherwise `ageInYears2`

`finalAgeInYears` is therefore a fallback-compatible coarse age field, not the only authoritative age value for analytics.

## Current DigitVA Data Reality

Current `va_submissions.va_data` records show that:

- all WHO 2022 age keys are usually present as JSON keys
- many rows populate multiple age representations at once
- these representations frequently do not numerically align if treated as additive components

Examples seen in current data include rows where:

- `ageInDays` and `ageInYears2` are both populated
- `ageInMonths` and `ageInYears2` are both populated
- `ageInDays`, `ageInMonths`, `ageInYears`, and `ageInYears2` are all populated

This is expected because:

- `ageInDays` and related fields come from the date-derived path
- `ageInYears2` comes from the manual age-group path

These fields are overlapping representations, not cumulative parts.

## Required Interpretation Rules

### Rule 1: Never add age components across paths

DigitVA must not add or combine:

- `ageInDays`
- `ageInMonths`
- `ageInYears`
- `ageInYears2`

as if they are separate cumulative components of the same age.

For example, a record with:

- `ageInDays = 720`
- `ageInMonths = 11`
- `ageInYears2 = 2`

must not be interpreted as `720 days + 11 months + 2 years`.

### Rule 2: Preserve raw age fields

DigitVA must preserve the raw ODK age fields in synced submission payloads.

Analytics layers may derive normalized age outputs, but they must not discard the underlying raw age fields needed for audit and debugging.

### Rule 3: Use precedence, not arithmetic combination

Analytics and reporting logic must choose a single age source per record using precedence rules.

## Normalization Policy For Analytics

### Neonates

For neonates, DigitVA must prefer:

1. `age_neonate_hours`
2. `age_neonate_days`
3. `ageInDays`
4. `finalAgeInYears` only as a coarse fallback if detailed neonatal fields are absent

If `age_neonate_days = 0` and `age_neonate_hours` is present, the hour value is the most precise age representation.

### Children

For children, DigitVA must prefer:

1. `ageInDays` when available
2. `ageInMonths` when days are unavailable
3. `ageInYears`
4. `ageInYears2`
5. `finalAgeInYears`

`ageInDays`, `ageInMonths`, and `ageInYears` should be treated as alternative date-derived representations of one age, not summed.

### Adults

For adults, DigitVA must prefer:

1. `ageInYears`
2. `ageInYears2`
3. `finalAgeInYears`

For adult analytics, day and month fields should not be used in preference to a populated year field.

### Coarse fallback

If more detailed age fields are unavailable, `finalAgeInYears` may be used as the stable coarse age field across forms.

## Age Band Policy

For DigitVA analytics and reporting, derived age bands must be:

- `neonate`: `<= 28 days`
- `child`: `29 days` to `< 15 years`
- `15_49y`: `>= 15 and < 50`
- `50_64y`: `>= 50 and < 65`
- `65_plus`: `>= 65`
- `unknown`: insufficient valid age data

These analytics age bands are DigitVA reporting bands. They are not the same as the raw WHO 2022 questionnaire routing groups.

## Raw Questionnaire Routing Group Policy

The raw WHO 2022 `age_group` field is a questionnaire-routing field and must not be treated as the final analytics age band.

Reasons:

- it may be blank when date-derived fields are available
- it reflects questionnaire selection behavior
- it uses WHO routing cutoffs, not DigitVA analytics cutoffs

DigitVA may retain `age_group` as `age_group_raw`, but must derive analytics age bands independently.

## Materialized View Policy

Any analytics materialized view for WHO 2022 submissions must include:

- raw age source fields used by the form
- a chosen normalized age source indicator
- normalized age outputs
- derived analytics age band

At minimum, the materialized view should include:

- `age_group_raw`
- `age_neonate_days`
- `age_neonate_hours`
- `age_in_days_raw`
- `age_in_months_raw`
- `age_in_years_raw`
- `age_in_years2_raw`
- `final_age_years_raw`
- `normalized_age_days`
- `normalized_age_years`
- `normalized_age_source`
- `analytics_age_band`

## Sync Flattening Policy

The current flattened `va_submissions.va_deceased_age` field is a coarse convenience field only.

It must not be treated as the only authoritative age field for:

- age-band analytics
- neonatal reporting
- child reporting
- age-quality checks
- future materialized views

Any new analytics work must prefer raw WHO 2022 age fields from `va_submissions.va_data`.

DigitVA now also stores sync-time normalized age fields on `va_submissions`:

- `va_deceased_age_normalized_days`
- `va_deceased_age_normalized_years`
- `va_deceased_age_source`

These fields:

- are derived from the same WHO 2022 precedence rules used for analytics
- preserve one chosen source per record for auditability
- do not replace the need to retain raw WHO age fields in `va_data`
- do not change the legacy meaning of `va_deceased_age`, which remains a coarse year field derived from `finalAgeInYears`

## SmartVA Preprocessing Requirements

### Problem

SmartVA WHO 2022 uses `age_neonate_days` and `age_neonate_hours` to classify neonate
cases and derive its internal age-group flags (`gen_5_4*`). It does not fall back to
`ageInDays` alone for very young deaths (≤ 28 days).

When submissions go through the **date-derived path**, `ageInDays` is correctly
populated (e.g. 3, 13 days) but `age_neonate_days`, `age_neonate_hours`, and
`age_group` are all null — because the form only sets these on the manual path.

SmartVA rejects such submissions with:
> "does not have valid age data and is being removed from the analysis"

Empirically confirmed across UNSW01 forms:
- 24 submissions rejected across UNSW01KA0101 (15) and UNSW01NC0101 (9)
- All had `ageInDays` ≤ 28 with null `age_neonate_days` / `age_group`
- Submissions with `ageInDays` > 28 and null `age_group` were processed correctly

### Required Preprocessing Rule

Before writing `smartva_input.csv`, `va_smartva_prepdata` must synthesize
`age_neonate_days` from `ageInDays` when all of the following are true:

1. `ageInDays` is present and numeric
2. `ageInDays` ≤ 28
3. `age_group` is blank
4. `age_neonate_days` is blank
5. `age_adult` is blank (confirms this is not a misclassified adult)

Synthesis rule:
```
age_neonate_days = int(ageInDays)
```

Zero-day cases (`ageInDays = 0`) are synthesized the same way. SmartVA may still
reject them as stillbirths — this is acceptable and should be recorded as
`smartva_rejected` failure with reason from `report.txt`, not as a missing-row failure.

### Non-neonate Cases

Submissions with `ageInDays` > 28 and null `age_group` do not require synthesis.
SmartVA correctly classifies child and adult cases from `ageInDays` alone.

## Verification Expectations

Any implementation of WHO 2022 age normalization must be verified against:

- current live/sample DigitVA submission data
- rows with multiple populated age representations
- neonatal rows with `age_neonate_days` and `age_neonate_hours`
- child rows with only date-derived fields
- adult rows with only `ageInYears2` / `finalAgeInYears`

## Implementation Follow-up

Before introducing a reporting materialized view based on WHO 2022 age fields, DigitVA should:

1. normalize numeric parsing for values stored as strings such as `1`, `1.0`, `76`, or `76.0`
2. encode one explicit precedence rule for normalized age selection
3. expose the chosen source field for auditability
4. keep raw age fields available for debugging and reconciliation
