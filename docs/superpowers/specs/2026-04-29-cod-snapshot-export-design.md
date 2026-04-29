---
title: COD Snapshot Export MV Design
doc_type: spec
status: proposed
owner: engineering
last_updated: 2026-04-29
---

# COD Snapshot Export MV Design

## Summary

This design adds a new submission-granular reporting materialized view that
centralizes the active coding snapshot for each VA submission, including:

- submission context and demographics needed for export
- latest active coder coding data
- latest active reviewer coding data
- authoritative final COD outcome
- active SmartVA result data
- WHO 2022 VA COD bucket mappings for human COD and SmartVA CODs
- active Narrative Quality Assessment (NQA) data
- Social Autopsy data where available

This MV becomes the primary reporting source for a new data-management export
endpoint focused on coded outcomes.

The change is additive. Existing analytics MVs and existing export endpoints
remain unchanged.

## Goals

- provide one reporting row per `va_sid`
- centralize active COD-related reporting logic in one place
- avoid repeated live-table joins for heavy export requests
- preserve reviewer/coder distinction and authoritative final-COD semantics
- expose WHO 2022 VA bucket mappings for each relevant COD source
- support export needs without changing existing CSV contracts

## Non-Goals

- replacing existing analytics MVs used for KPI/dashboard counts
- storing coding history or multiple versions per submission in the new MV
- changing workflow semantics, COD authority semantics, or SmartVA generation
- introducing a new user-facing editor or dashboard beyond the export endpoint

## Current State

The repository currently has three analytics MVs:

- `va_submission_analytics_core_mv`
- `va_submission_analytics_demographics_mv`
- `va_submission_cod_detail_mv`

These provide:

- submission scope and workflow metadata
- demographics and SmartVA/human-COD presence flags
- active final COD and SmartVA top-cause projection

They do not currently provide a complete export-ready COD snapshot. Missing
export-facing data includes:

- latest active coder and reviewer identity data
- active Step 1 and Step 2 coding payload details
- active NQA data
- Social Autopsy data
- WHO 2022 VA bucket mappings for all COD sources
- a single canonical current COD snapshot object for reporting

## Proposed Design

### New Materialized View

Add a new materialized view:

- `va_submission_cod_snapshot_mv`

Characteristics:

- one row per `va_sid`
- active/current records only
- read-only from application code
- refreshed by the same analytics refresh flow used for current reporting MVs

### Why A New MV

This MV has a different responsibility from the existing analytics MVs:

- current analytics MVs support filtering, counts, and compact COD analytics
- the new MV supports export/reporting of the active submission coding snapshot

Keeping it separate avoids turning the existing COD detail MV into a very wide,
mixed-purpose reporting object.

## Data Contract

### Base Submission Fields

The MV should include:

- `va_sid`
- `project_id`
- `site_id`
- `form_id`
- `submission_at`
- `submission_date`
- `workflow_state`
- `narration_language`
- `sex`
- raw or normalized age fields needed for export
- `narrative_text`
- `coded_at_authoritative`

If the existing schema stores multiple narrative-bearing fields, the MV should
project the same narrative value currently treated as the export narrative for
data-management reporting. Do not silently invent new narrative semantics.

### Latest Coder Snapshot

The MV should preserve the latest active coder-owned data independently from
reviewer-owned or authoritative data.

Include:

- `coder_user_id`
- `coder_name`
- latest coder step timestamps
- latest active coder Step 1 fields needed by export
- latest active coder Step 2 fields needed by export
- latest active coder final COD text
- latest active coder final ICD
- latest active coder final save timestamp
- latest coder WHO 2022 section
- latest coder WHO 2022 bucket

### Latest Reviewer Snapshot

The MV should preserve the latest active reviewer-owned data independently from
coder-owned or authoritative data.

Include:

- `reviewer_user_id`
- `reviewer_name`
- latest reviewer final COD text
- latest reviewer final ICD
- latest reviewer final save timestamp
- latest reviewer WHO 2022 section
- latest reviewer WHO 2022 bucket

### Authoritative Final Snapshot

The MV should separately expose the authoritative final COD used for reporting.

Include:

- `authoritative_source` with values such as `coder` or `reviewer`
- `authoritative_cod_text`
- `authoritative_icd`
- `authoritative_saved_at`
- `authoritative_who_bucket_section`
- `authoritative_who_bucket`

Semantics:

- `coded_at_authoritative` should match `authoritative_saved_at`
- authoritative COD follows the existing final-COD authority model
- no workflow or authority behavior changes are introduced here

### SmartVA Snapshot

The MV should include the active SmartVA result for the submission.

Include:

- `smartva_result_for`
- `smartva_age`
- `smartva_gender`
- `smartva_cause1`
- `smartva_cause1_icd`
- `smartva_cause1_who_bucket_section`
- `smartva_cause1_who_bucket`
- `smartva_cause2`
- `smartva_cause2_icd`
- `smartva_cause2_who_bucket_section`
- `smartva_cause2_who_bucket`
- `smartva_cause3`
- `smartva_cause3_icd`
- `smartva_cause3_who_bucket_section`
- `smartva_cause3_who_bucket`

### Narrative Quality Assessment

The MV should include active NQA data where present.

Include export-relevant fields only, for example:

- active NQA owner identity if available
- score
- rating
- key boolean/ordinal fields currently used operationally
- active NQA save timestamp

The implementation must follow the current payload-aware NQA policy and expose
only the active NQA row relevant to the current payload snapshot.

### Social Autopsy

The MV should include Social Autopsy data where present.

Scope:

- include the currently active export-relevant Social Autopsy fields
- keep this submission-granular
- do not expand into multi-row Social Autopsy history

### Assignment Data

The MV should include active assignment or actor identity data needed for
reporting where available.

This includes:

- currently assigned doctor/coder identity if such assignment is explicitly
  stored
- latest coder and reviewer names even when no active assignment exists

## WHO 2022 Bucket Mapping Rules

Bucket mapping in the new MV must use the built-in `WHO 2022 VA` scheme.

Mappings must be carried separately for:

- latest coder final ICD
- latest reviewer final ICD
- authoritative final ICD
- SmartVA primary ICD
- SmartVA secondary ICD
- SmartVA tertiary ICD

Rules:

- map each ICD independently
- do not infer one source's bucket from another source's ICD
- if an ICD has no bucket mapping, leave the bucket fields null/empty rather
  than inventing a fallback

## Export Endpoint

Add a new additive endpoint under the existing data-management export family,
for example:

- `/api/v1/data-management/submissions/export-coded-cod-snapshot.csv`

Requirements:

- same data-manager access control as current export endpoints
- same filter contract as current data-management exports
- one CSV row per submission
- existing export endpoints remain unchanged
- cached/exported using the same response pattern as current CSV exports

## Query Strategy

The export query should:

- use the same project/site scoping rules as current data-management reporting
- use the same dashboard filters
- read primarily from `va_submission_cod_snapshot_mv`
- join existing analytics MVs only if needed for compatibility or filtering

The long-term preferred shape is:

- export columns are sourced from the new snapshot MV
- filtering can continue to rely on the current analytics MV contract if that
  keeps the route logic stable

## Refresh Model

The new MV should refresh alongside the existing analytics/reporting MVs.

Requirements:

- integrate with current analytics MV refresh orchestration
- keep refresh idempotent and repeatable
- do not require destructive resets

If refresh cost becomes material later, optimization can be handled separately.
That is not a blocker for this change.

## Backward Compatibility

- no changes to current export endpoints or filenames
- no changes to current workflow, SmartVA, or coding semantics
- no changes to authority resolution behavior
- additive reporting surface only

## Risks

### Schema And Query Width

The MV can become very wide because Step 1, Step 2, NQA, Social Autopsy, and
SmartVA each contribute multiple export columns.

Mitigation:

- include only export-relevant fields
- keep naming explicit and grouped by source prefix
- avoid copying unused operational JSON blindly

### Semantics Drift

Latest coder, latest reviewer, and authoritative final data must remain
distinct.

Mitigation:

- separate column prefixes by source
- write tests that verify these fields differ when reviewer authority exists

### Bucket Mapping Drift

Bucket mapping must consistently use the WHO 2022 VA scheme.

Mitigation:

- resolve the scheme explicitly by code/name in one place
- add tests for bucket mapping of coder, reviewer, authoritative, and SmartVA
  ICDs

## Verification Strategy

Implementation should include focused tests for:

- one-row-per-submission behavior
- latest coder data preserved when reviewer data exists
- latest reviewer data preserved separately
- authoritative final COD derived correctly
- `coded_at_authoritative` tracks authoritative final save time
- SmartVA cause bucket mapping for cause1, cause2, and cause3
- human COD bucket mapping for coder, reviewer, and authoritative ICDs
- Social Autopsy projection when present
- active NQA projection when present
- data-manager export scoping and filtering

## Files Expected To Change During Implementation

Likely files:

- `app/services/submission_analytics_mv.py`
- `migrations/versions/<new_revision>_add_submission_cod_snapshot_mv.py`
- `app/services/data_management_service.py`
- `app/routes/api/data_management.py`
- `app/tasks/export_tasks.py`
- `tests/services/test_submission_analytics_mv.py`
- `tests/routes/test_data_manager_dashboard.py`
- `docs/policy/<new_or_updated_policy_doc>.md`
- `docs/current-state/submission-analytics.md`
- `docs/current-state/data-manager-dashboard.md`

## Policy And Documentation Follow-Through

Because this changes reporting behavior, implementation must also:

- create or update a policy doc under `docs/policy` for the COD snapshot export
  baseline
- update `docs/current-state/submission-analytics.md`
- update `docs/current-state/data-manager-dashboard.md`

## Open Implementation Decisions

These should be settled during implementation planning based on the existing
schema:

- exact source fields for export narrative text
- exact Step 1 and Step 2 column list
- exact Social Autopsy field list to expose
- exact active NQA field list to expose
- whether the export route filters directly on the new MV or continues using
  the current analytics MV joins for consistency

## Recommended Plan Direction

Implementation should proceed in this order:

1. define the policy baseline for the new COD snapshot export behavior
2. add failing tests for MV semantics and export contract
3. add the new materialized view and refresh wiring
4. add the new CSV export service and route
5. update current-state docs
6. verify with focused tests and export endpoint coverage
