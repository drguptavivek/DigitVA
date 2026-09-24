---
title: Data Management COD Snapshot Export
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-24
---

# Data Management COD Snapshot Export

## Purpose

This policy defines the baseline behavior for the data-management coded COD
snapshot export and its backing reporting materialized view.

## Baseline

- the coded COD snapshot export is submission-granular: one row per `va_sid`
- it reports only active/current COD-facing records, not history
- it preserves three distinct human-COD views when available:
  - latest active coder data
  - latest active reviewer data
  - authoritative final COD outcome
- `coded_at_authoritative` means the saved timestamp of the authoritative final
  COD outcome, not merely the latest coder Step 2 save

## Included Data

The reporting snapshot may include:

- project, site, form, submission, workflow, and demographic context
- active payload `unique_id` and `survey_block` values when present
- narrative text and narration language
- latest active coder Step 1 and Step 2 COD fields
- latest active reviewer final COD fields
- authoritative final COD fields
- active SmartVA result fields
- active Narrative Quality Assessment fields, including the individual scored
  NQA question columns
- active Social Autopsy fields, including the app-owned analysis summary and
  the active payload's raw `sa*` questionnaire fields
- active coder/reviewer assignment names where available

## WHO 2022 Bucket Mapping

Buckets come from the `WHO_2022_VA_2026` scheme for every death (owner,
2026-09-24; `docs/policy/icd10-to-icd11-transition.md` decisions 6 and 7).
Each value is bucketed through the rows of its own classification, decided
by its code shape: ICD-10 values through the `icd10` rows, ICD-11 values
through the `icd11` rows (exact code, then nearest catalogue ancestor; a
post-coordinated value by its first stem). SmartVA ICDs are ICD-10. No
crosswalk is used. Each bucket carries a provenance value: `icd10`,
`icd11_native`, `unmapped` (a value with no bucket), or empty (no value).

WHO 2022 VA COD bucket mapping must be derived independently for:

- latest coder final ICD
- latest reviewer final ICD
- authoritative final ICD
- SmartVA cause 1 ICD
- SmartVA cause 2 ICD
- SmartVA cause 3 ICD

If no WHO 2022 mapping exists for a given ICD, the export must leave the bucket
fields empty rather than infer a fallback.

For Step 1 reporting:

- the export should include the preserved latest coder Step 1 assessment for the
  submission when one exists
- final COD submission does not itself invalidate Step 1 reporting data

When a historical ICD is present in coding data and
`map_icd10_legacy_reporting_aliases` defines a reporting-code replacement, the
bucket lookup must use that reporting ICD. This reporting-only normalization
must not overwrite the raw coder, reviewer, authoritative, or SmartVA ICD
columns exposed by the snapshot export.

## Authority Semantics

- authoritative COD follows the existing final-COD authority model
- reviewer authority takes precedence when explicitly set
- if no explicit authority row exists, reporting may fall back to the latest
  active reviewer final COD, then the latest active coder final COD
- this export does not change any workflow or authority behavior; it only
  reports the current state
