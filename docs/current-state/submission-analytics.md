---
title: Submission Analytics Materialized View
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-25
---

# Submission Analytics Materialized Views

## Purpose

DigitVA now provides three focused PostgreSQL materialized views:

- `va_submission_analytics_core_mv`
- `va_submission_analytics_demographics_mv`
- `va_submission_cod_detail_mv`

Together they support analytics, trend charts, and reporting queries without
running repeated live joins across operational workflow and coding tables.

The materialized-view layer is:

- one row per `va_sid`
- additive to the current operational schema
- read-only from application code
- refreshed asynchronously

## Source Tables

The materialized view reads from:

- `va_submissions`
- `va_forms`
- `va_submission_workflow`
- `va_initial_assessments`
- `va_final_assessments`
- `va_reviewer_final_assessments`
- `va_final_cod_authority`
- `va_smartva_results`

## Included Dimensions

Across the three views, DigitVA stores:

- project, site, and form identifiers
- submission timestamps and day/week/month buckets
- workflow state
- ODK review state
- ODK sync issue state
- normalized demographic fields
- human coding outputs
- SmartVA outputs

## Demographics MV

`va_submission_analytics_demographics_mv` includes:

- `va_sid`
- `va_narration_language`
- `sex`
- `analytics_age_normalized_days`
- `analytics_age_band`
- `has_smartva`
- `has_human_initial_cod`
- `has_human_final_cod`

It derives analytics age from sync-time normalized fields already stored on
`va_submissions`:

- `va_deceased_age_normalized_days`
- `va_deceased_age_normalized_years`
- `va_deceased_age_source`

The derivation rules follow the policy in
[WHO 2022 Age Derivation Policy](../policy/who-2022-age-derivation.md).

Important current behavior:

- `analytics_age_normalized_days` is sourced directly from
  `va_submissions.va_deceased_age_normalized_days`
- the winning WHO age source is stored on
  `va_submissions.va_deceased_age_source`
- child and adult ages are normalized using source precedence, not additive
  combination
- raw `age_group` from the XLSForm is not treated as the final analytics age
  band

## Human COD And SmartVA

The view includes:

- latest active initial COD fields
- authoritative final human COD
- parsed human ICD prefixes from stored COD strings
- active SmartVA outputs and ICD codes

Final human COD resolution follows the current authority model:

- reviewer final COD pointed to by `va_final_cod_authority` when present
- otherwise coder final COD pointed to by `va_final_cod_authority`
- fallback to latest active reviewer final COD, then latest active coder final
  assessment, if no authority row is present

## Refresh Model

The materialized view is refreshed by Celery.

Current refresh behavior:

- hourly Celery Beat refresh task
- task name: `app.tasks.sync_tasks.refresh_submission_analytics_mv_task`
- tracked in `va_sync_runs` with `triggered_by = "analytics_mv"`

The refresh helpers are implemented in
[submission_mv.py](../../app/services/analytics/submission_mv.py).

## Indexes

The materialized views have indexes for common analytics filters, including:

- `va_sid`
- `submission_date`
- `(project_id, site_id)`
- `workflow_state`
- `odk_review_state`
- `analytics_age_band`
- `sex`
- `final_icd`
- `smartva_cause1_icd`

## Current Intended Consumers

The materialized view is intended for:

- reporting endpoints
- dashboard analytics APIs
- future project/site trend visualizations
- SmartVA versus human-COD comparison analysis

Not all existing dashboard endpoints have been migrated to use the view yet.
Some current operational dashboard queries still read directly from live tables.
The analytics MV itself is now reviewer-authority-aware; remaining legacy
reporting cleanup is outside the view.

## Verification

The materialized-view behavior is covered by focused tests in:

- [test_submission_analytics_mv.py](../../tests/services/test_submission_analytics_mv.py)

The tested cases include:

- same-day neonatal deaths with hour-level age
- child normalization from `ageInDays`
- authoritative final human COD selection
- reviewer final COD precedence over coder final COD in analytics output
- ICD parsing for human and SmartVA outputs
