---
title: COD Bucket Reporting Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-21
---

# COD Bucket Reporting Policy

## Purpose

Define how DigitVA classifies coded submissions into reporting-oriented
cause-of-death buckets such as `SRS India` and `CMEA10`.

## Policy

1. Authoritative coding data remains the submission's final ICD outcome.
2. Reporting bucket classification is a separate, versioned mapping layer.
3. Changing a bucket mapping scheme must not mutate coder or reviewer final COD
   records on submissions.
4. Multiple reporting schemes may coexist.
5. A scheme may define different hierarchy depth and age-scoped trees.
6. Deleting a bucket node must never mutate authoritative submission COD rows.
7. When deleting a bucket node, the operator must choose one of:
   - unmap all affected ICD codes
   - move all affected ICD codes to an `Unmapped` replacement leaf
8. Deleting a non-leaf bucket cascades to all descendant bucket nodes.
9. If the operator chooses `move_to_unmapped` for a non-leaf delete, DigitVA
   must create an `Unmapped` replacement chain in place of the deleted branch
   and move all affected ICD mappings to the replacement leaf.
10. The admin COD bucket panel must support JSON export per scheme.
11. Scheme export must include the scheme metadata, all age bands, all hierarchy
    nodes, and all ICD mappings for that scheme.
12. The ICD picker used while maintaining COD bucket mappings must read from
    `mas_icd10_2019_2`, not legacy `va_icd_codes`.
13. The COD bucket ICD picker must return active three-character or detailed
    ICD rows from the master table, without applying age- or sex-based
    filtering. Rows that are not currently assignable in coding must still be
    available for COD bucket mapping and must be explicitly marked as
    `Currently not assignable in coding`.
14. The admin COD bucket editor must expose a scheme-level grid of active
    three-character or detailed ICD rows that are not mapped anywhere in the
    current scheme, across all age groups, shown as a single ICD code list
    rather than split three-character vs detailed columns.
15. Rows in that scheme-level unmapped ICD grid that are not currently
    assignable in coding must remain bulk-mappable and must be explicitly
    marked as `Currently not assignable in coding`.
16. The scheme-level unmapped ICD grid must support bulk allocation by letting
    the operator choose a target age band and a target disease-level leaf
    within that scheme, then map multiple selected ICD codes in one action.

## Scheme model

DigitVA stores reporting schemes as master data:

- `mas_cod_bucket_schemes`
- `mas_cod_bucket_nodes`
- `map_icd_cod_buckets`

Supported examples:

- `SRS India`
- `CMEA10`

## Age scope policy

Age scope belongs to the reporting mapping, not to the submission's coded ICD
record.

Current SRS scopes:

- `adult_over5y`
- `child_1_59m`
- `neonate`

Current CMEA10 scope:

- no age scope

Age band bounds are interpreted as:

- lower bound: inclusive (`>=`)
- upper bound: exclusive (`<`)
- every stored age band must have explicit lower and upper bounds
- DigitVA must not persist open-ended `NULL` age ranges for COD schemes
- built-in open-ended schemes use an explicit upper cap of `120 years`

Age band normalization for COD reporting uses these fixed conversions:

- `days` -> `1 day`
- `months` -> `365 / 12 days`
- `years` -> `365 days`

Because month-to-day conversion is approximate, age-band overlap and gap checks
in the admin creator are operator feedback, not hard blockers.

## Aggregation policy

Bucketed COD aggregation must be driven from authoritative final ICD outcomes,
not from draft or non-authoritative coding rows.

Current aggregate inputs:

- authoritative `final_icd`
- demographics-derived age band
- active COD bucket mapping scheme
- per-age-group count of final ICDs that do not match any active scheme category

Unmatched final ICDs must not be merged into hierarchy rows. The reporting UI
must show them as a note for the relevant age group stating that those
submitted CODs did not match any category and were dropped from the displayed
table. That note must offer a modal tabulation of the dropped ICD codes for the
selected age group, split into:

- ICD codes not included in the selected scheme's CoD categories for that age group
- ICD codes not eligible for coding

## Change policy

If the group, sub-group, or leaf bucket for an ICD code changes:

- update the mapping scheme version
- refresh aggregate outputs
- do not rewrite historical submission COD rows

This preserves auditability and keeps coding and reporting concerns separate.

## Deletion policy

COD bucket node deletion affects only reporting taxonomy master data:

- `mas_cod_bucket_nodes`
- `map_icd_cod_buckets`

It must not rewrite any submission coding records.

Deletion behavior is:

- leaf delete + `unmap`
  - delete the leaf
  - delete associated ICD mappings
- leaf delete + `move_to_unmapped`
  - delete the leaf
  - create or reuse an `Unmapped` replacement leaf under the same parent
  - move associated ICD mappings there
- higher-level delete + `unmap`
  - delete the selected node and all descendants
  - delete all ICD mappings from descendant leaves
- higher-level delete + `move_to_unmapped`
  - delete the selected node and all descendants
  - create or reuse an `Unmapped` replacement branch in the same parent
    position
  - move all descendant ICD mappings to the replacement leaf
