---
title: Submission Analytics Materialized View
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-18
---

# Submission Analytics Materialized View

## Purpose

DigitVA now provides a PostgreSQL materialized view named `va_submission_analytics_mv`.

It exists to support analytics, trend charts, and reporting queries without
running repeated live joins across operational workflow and coding tables.

The view is:

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
- `va_final_cod_authority`
- `va_smartva_results`

## Included Dimensions

The view includes:

- project, site, and form identifiers
- submission timestamps and day/week/month buckets
- workflow state
- ODK review state
- ODK sync issue state
- normalized demographic fields
- human coding outputs
- SmartVA outputs

## Age Normalization

The view does not expose raw WHO 2022 age source fields.

Instead it stores normalized analytics-ready age outputs:

- `normalized_age_hours`
- `normalized_age_days`
- `normalized_age_months`
- `normalized_age_years`
- `normalized_age_source`
- `age_precision`
- `analytics_age_band`

The derivation rules follow the policy in
[WHO 2022 Age Derivation Policy](../policy/who-2022-age-derivation.md).

Important current behavior:

- same-day neonatal deaths preserve hour-level age resolution
- child and adult ages are normalized using source precedence, not additive combination
- raw `age_group` from the XLSForm is retained only indirectly through derived analytics logic and is not treated as the final reporting age band

## Human COD And SmartVA

The view includes:

- latest active initial COD fields
- authoritative final human COD
- parsed human ICD prefixes from stored COD strings
- active SmartVA outputs and ICD codes

Final human COD resolution follows the current authority model:

- explicit `va_final_cod_authority` pointer when present
- latest active final assessment fallback when no authority row is present

## Refresh Model

The materialized view is refreshed by Celery.

Current refresh behavior:

- hourly Celery Beat refresh task
- task name: `app.tasks.sync_tasks.refresh_submission_analytics_mv_task`
- tracked in `va_sync_runs` with `triggered_by = "analytics_mv"`

The refresh helper is implemented in
[submission_analytics_mv.py](../../app/services/submission_analytics_mv.py).

## Indexes

The materialized view has indexes for common analytics filters, including:

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

## Verification

The materialized view behavior is covered by focused tests in:

- [test_submission_analytics_mv.py](../../tests/services/test_submission_analytics_mv.py)

The tested cases include:

- same-day neonatal deaths with hour-level age
- child normalization from `ageInDays`
- authoritative final human COD selection
- ICD parsing for human and SmartVA outputs
