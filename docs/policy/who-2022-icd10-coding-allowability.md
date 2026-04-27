---
title: WHO 2022 ICD-10 Coding Allowability Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-27
---

# WHO 2022 ICD-10 Coding Allowability Policy

## Purpose

This policy defines the ICD-10 2019-2 rows that are selectable during WHO 2022
verbal autopsy ICD coding.

This policy controls ICD coding search and selection only. COD bucket grouping,
road-traffic versus other-transport bucket mapping, and ambiguous bucket
resolution are out of scope for this step.

## Baseline Source

The WHO 2022 VA crosswalk workbook is the baseline source for ICD coding
allowability. A generated policy JSON is a full replacement import payload, not
an overlay. When imported, editable ICD rows absent from the generated JSON
become not selectable through the existing overwrite-style import behavior.

Default allowed WHO ICD rows use:

- `is_coding_selectable=true`
- `sex_selectable=both`
- `age_group_selectable=all`

Exception rules override those defaults.

## Age Groups

ICD coding age allowability supports:

- `all`
- `neonate`
- `infant`
- `child`
- `adult`

Submission age classification is:

- `neonate`: `0` to `<28 days`
- `infant`: `28 days` to `<365 days`
- `child`: `365 days` to `<12 years`
- `adult`: `>=12 years`

Policy matching is exact-or-all. A code marked `all` is available to every age
group. A code marked `infant` is available only to submissions classified as
`infant`.

## Allowability Rules

Allowed ICD rows are active ICD10-2019-2 editable rows referenced by
`WHO_2022_VA_Crosswalk.xlsx`, after expanding raw ICD expressions against the
existing ICD10 master.

Expansion preserves the granularity shown by WHO:

- a three-character code such as `C50` selects only `C50`
- a three-character range such as `C51-C58` selects only three-character rows in
  that range
- a dotted code such as `I11.0` selects only that dotted code
- a dotted range such as `V10.4-V10.9` selects only dotted rows in that dotted
  range

Never selectable:

- `S00-T99`, including all active editable rows in that range

Road-traffic footnote codes are selectable for both sexes and all ages. This
only affects ICD coding allowability; road-traffic versus other-transport COD
bucket mapping is deferred.

Neonate-only, both sexes:

- `P05`, `P07`
- `P20-P22`
- `P23-P24`
- `P36`
- `A33`
- `Q00-Q99`
- `P00-P04`
- `P08-P15`
- `P25-P35`
- `P37-P94`
- `P96`
- `P95`

Infant-only, both sexes:

- `R95`

Female-only, adult-only:

- all WHO maternal `O` code rows

Sex-specific neoplasms:

- `C51-C58`: female-only, all ages
- `C60-C63`: male-only, all ages
- `C50`: both sexes, all ages

## Overlap Rules

Never-selectable rules win over all other rules. Age and sex exceptions win over
default WHO allowability. Within exceptions, the most restrictive applicable
rule wins. Bucket ambiguity may be recorded in notes where useful but is not
resolved by this policy.
