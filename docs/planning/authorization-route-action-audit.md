---
title: Authorization Route Action Audit
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-04-22
---

# Authorization Route Action Audit

## Purpose

Track which routes have been migrated to the central action-based authorization
layer.

This document is the implementation audit companion to:

- [../policy/authorization-policy.md](../policy/authorization-policy.md)
- [access-control-grants-design.md](access-control-grants-design.md)

## First Migrated Slice

Implemented and startup-validated:

| Blueprint | Route family | Action family |
| --- | --- | --- |
| `data_management` | dashboard, KPI shell, CoD reporting | `dm_dashboard_view`, `dm_kpi_dashboard_view`, `cod_dashboard_view` |
| `data_management` | submission read-only view, ODK edit | `dm_submission_view`, `dm_submission_odk_edit` |
| `data_management` | user and grant management | `dm_user_management_*`, `dm_manage_*` |
| `api_v1.data_management_api` | submissions grid and exports | `dm_submissions_view`, `dm_export_view` |
| `api_v1.data_management_api` | KPI/filter/reporting reads | `dm_kpi_view`, `dm_filter_options_view`, `dm_project_site_submissions_view`, `dm_sync_runs_view` |
| `api_v1.data_management_api` | sync and workflow mutations | `dm_form_sync`, `dm_submission_sync`, `dm_submission_*` |
| `api_v1.cod_buckets_api` | CoD dashboard schemes and aggregates | `cod_dashboard_view` |
| `coding` | dashboard, allocation entrypoints, demo, submission view | `coding_dashboard_view`, `coding_start`, `coding_resume`, `coding_pick`, `coding_recode_start`, `coding_demo_start`, `coding_submission_view` |
| `api_v1.coding_api` | allocation, availability, stats, history, project options, admin maintenance | `coding_allocation_*`, `coding_available_view`, `coding_stats_view`, `coding_history_view`, `coding_projects_view`, `coding_admin_override_recode`, `coding_mark_reviewer_eligible`, `coding_debug_stats_view` |
| `reviewing` | dashboard, start, resume, reviewed submission view | `reviewing_dashboard_view`, `reviewing_start`, `reviewing_resume`, `reviewing_submission_view` |
| `api_v1.reviewing_api` | allocation read/create and finalization | `reviewing_allocation_view`, `reviewing_allocation_create`, `reviewing_finalize` |
| `va_form` | dynamic submission section rendering, triage, user notes, coder/reviewer supporting forms, attachment/media | `va_form_section_view_*`, `dm_triage_*`, `reviewing_nqa_save`, `coding_initial_assessment_save`, `coding_final_assessment_submit`, `coding_not_codeable_submit`, `submission_user_note_save`, `workflow_history_view`, `attachment_view` |
| `api_v1.nqa_api` | Narrative QA save | `submission_narrative_qa_save` |
| `api_v1.so_api` | Social Autopsy save | `submission_social_autopsy_save` |
| `api_v1.workflow` | workflow event history | `workflow_events_view` |
| `api_v1.analytics` | analytics time series, demographics, workflow, COD, MV refresh | `dm_kpi_view`, `dm_analytics_refresh` |
| `api_v1.dm_kpi_*` | DM KPI read APIs, cache bust, dashboard refresh | `dm_kpi_view`, `dm_kpi_cache_bust`, `dm_kpi_refresh` |

## Verification

The first migrated slice is verified by:

- startup validation that migrated routes have action mappings
- TOML validation that every action has roles, scope, resource, and reason
- focused automated tests covering:
  - policy loading
  - data-manager user/grant routes
  - data-manager dashboard and sync/reporting routes
  - analytics and DM KPI read/refresh routes
  - coding dashboard and allocation routes
  - reviewing dashboard, allocation, finalize, and reviewer review routes
  - `va_form` attachments, reviewer review, demo final COD, and DM triage routes
  - Narrative QA and Social Autopsy APIs for coding and reviewing sessions

## Deferred Blueprints

Still on legacy route auth:

- `api_v1.icd10_api`
