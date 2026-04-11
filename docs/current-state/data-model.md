---
title: Current Data Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-11
---

# Current Data Model

## Summary

The current model is centered on:

- `Project`
- `Site`
- `Form`
- `Submission`

with workflow state attached to submissions.

## Submission Identity

Current submission identifiers serve different purposes:

- `va_sid`
  - canonical local technical submission id
  - built as `{KEY}-{form_id.lower()}`
  - `KEY` is the stable ODK submission key (`__id` in OData)
- displayed `VA Form ID`
  - business-facing identifier shown in the UI
  - currently rendered from `va_uniqueid`
- `instanceID`
  - stored as ODK metadata
  - not the canonical local sync identity

Current rule:

- DigitVA identity and payload lineage are anchored on ODK `KEY`
- `instanceID` may change across edited versions and must not be treated as the
  primary local identifier

This is currently implemented as a single-project-first schema.

## Core Master Tables

### `va_research_projects`

Purpose:

- stores app project metadata

Key fields:

- `project_id`
- `project_code`
- `project_name`
- `project_nickname`
- `project_status`
- `narrative_qa_enabled`
- `social_autopsy_enabled`
- `coding_intake_mode`
- `demo_training_enabled`
- `demo_retention_minutes`

Current role:

- top-level project master, but effectively used in a one-project deployment model
- also stores project-level workflow toggles such as Narrative QA enablement,
  Social Autopsy analysis enablement, and coder intake mode
- now also stores demo/training project behavior:
  - whether the project is an open training pool
  - how many minutes demo-created coding artifacts should remain active before
    cleanup

### `va_sites`

Purpose:

- stores site metadata

Key fields:

- `site_id`
- `project_id`
- `site_name`
- `site_abbr`
- `site_status`

Current behavior:

- each site belongs to exactly one project because `project_id` is stored directly on the site row

Current limitation:

- sites are not modeled as reusable across multiple projects

### `va_forms`

Purpose:

- stores app form identity and ODK mapping

Key fields:

- `form_id`
- `project_id`
- `site_id`
- `odk_form_id`
- `odk_project_id`
- `form_type`
- SmartVA-related flags and country settings
- `form_status`

Current behavior:

- this table combines:
  - app-side business identity
  - project/site assignment
  - standardized form meaning
  - ODK source identity

Current convention:

- `form_id` is a synthetic internal key such as `UNSW01NC0101`
- it effectively encodes project, site, and a sequence/version

Current runtime role:

- `va_forms` is still the compatibility registry used by submissions, media paths,
  and permission queries
- active sync scope now comes from `map_project_site_odk`, and sync materializes or
  updates matching `va_forms` rows as needed

## Submission Table

### `va_submissions`

Purpose:

- stores imported ODK submissions after preprocessing

Key fields:

- `va_sid`
- `va_form_id`
- `va_submission_date`
- `va_odk_updatedat`
- `va_data_collector`
- `va_odk_reviewstate`
- `va_sync_issue_code`
- `va_sync_issue_detail`
- `va_sync_issue_updated_at`
- `va_instance_name`
- `va_uniqueid_real`
- `va_uniqueid_masked`
- `va_consent`
- `va_narration_language`
- `va_deceased_age`
- `va_deceased_age_normalized_days`
- `va_deceased_age_normalized_years`
- `va_deceased_age_source`
- `va_deceased_gender`
- `va_data`
- `va_summary`
- `va_catcount`
- `va_category_list`

Current behavior:

- `va_form_id` points to `va_forms.form_id`
- `va_data` holds the processed ODK row as JSONB
- additional structured and derived fields are extracted for workflow and UI use
- normalized age fields store sync-time WHO age precedence outputs for downstream analytics
- `va_odk_reviewstate` mirrors ODK Central review state locally for dashboard visibility
- `va_sync_issue_*` captures local sync-health markers such as `missing_in_odk`
- coder-ready counting paths are indexed for common filters:
  - `va_form_id`
  - `lower(va_narration_language)`
  - join key `va_sid`

## Workflow Tables

### `va_allocations`

Purpose:

- reserves one submission for one user for coding or review

Key fields:

- `va_sid`
- `va_allocated_to`
- `va_allocation_for`
- `va_allocation_status`
- timestamps

### `va_submission_workflow`

Purpose:

- stores one canonical local workflow-state row per submission

Key fields:

- `va_sid`
- `workflow_state`
- `workflow_reason`
- `workflow_updated_by_role`
- `workflow_updated_by`
- `workflow_created_at`
- `workflow_updated_at`

Current behavior:

- this table is additive and coexists with legacy workflow tables
- current rows are backfilled from active legacy records
- current route integration updates the row on:
  - coder allocation start
  - initial COD submit
  - final COD submit
  - coder Not Codeable submit
  - data-manager Not Codeable submit
  - sync-created submissions
  - stale coding allocation release
- coder dashboard availability and coder intake selection now read this table
- data-manager triage also writes directly to this table
- completion history and recode behavior still rely on legacy workflow tables
  in parallel, so this table is the canonical state store under migration, not
  yet the sole source of truth
- coder-ready workflows are additionally indexed on `(workflow_state, va_sid)`
  to reduce join/filter cost in coder and dashboard APIs

### `va_icd_codes`

Purpose:

- stores searchable ICD code catalog entries for coding forms

Key fields:

- `icd_code`
- `icd_to_display`
- `category`

Current behavior:

- API search supports both code-prefix and display-text matching
- performance indexes include:
  - `lower(icd_code)` (prefix/code search)
  - `gin(lower(icd_to_display) gin_trgm_ops)` for text matching

### `va_initial_assessments`

Purpose:

- first coding pass by coder

Key fields:

- `va_sid`
- `va_iniassess_by`
- `va_immediate_cod`
- `va_antecedent_cod`
- `va_other_conditions`
- `va_iniassess_status`

### `va_final_assessments`

Purpose:

- final coding outcome by coder

Key fields:

- `va_sid`
- `payload_version_id`
- `va_finassess_by`
- `source_initial_assessment_id`
- `va_conclusive_cod`
- `va_finassess_remark`
- `va_finassess_status`
- `demo_expires_at`

Current behavior:

- this table still stores the underlying coder final-COD records
- multiple historical rows may now exist for the same submission across recode
  episodes
- coder final-COD rows are now stamped with the submission's current
  `active_payload_version_id`
- coder final-COD rows now store explicit linkage to the exact Step 1 draft
  used during final submit via
  `source_initial_assessment_id -> va_initial_assessments.va_iniassess_id`
- the active row alone is no longer the sole authority signal during the
  workflow migration
- normal coding leaves `demo_expires_at` null
- demo coding stamps a temporary expiry timestamp
- admin-started demo sessions on ordinary projects use a 6-hour expiry
- `demo_training_enabled` projects use `demo_retention_minutes`, default
  10 minutes

### `va_reviewer_final_assessments`

Purpose:

- reviewer-owned final coding outcome after reviewer secondary coding

Key fields:

- `va_sid`
- `payload_version_id`
- `va_rfinassess_by`
- `va_conclusive_cod`
- `supersedes_coder_final_assessment_id`
- `va_rfinassess_status`

Current behavior:

- reviewer final-COD rows are now stamped with the submission's current
  `active_payload_version_id`
- reviewer final-COD history is stored separately from coder final-COD history
- active reviewer final-COD rows may supersede coder final-COD rows in
  authority resolution

### `va_smartva_runs`

Purpose:

- stores one durable SmartVA execution attempt per submission payload version

Key fields:

- `va_smartva_run_id`
- `va_sid`
- `payload_version_id`
- `trigger_source`
- `va_smartva_outcome`
- `va_smartva_failure_stage`
- `va_smartva_failure_detail`
- `run_metadata`
- run timestamps

Current behavior:

- one row is written per SmartVA attempt
- both successful and failed attempts are preserved
- each run is linked to the submission payload lineage through
  `payload_version_id`

### `va_smartva_run_outputs`

Purpose:

- stores emitted SmartVA output rows for a SmartVA run

Key fields:

- `va_smartva_run_output_id`
- `va_smartva_run_id`
- `output_kind`
- `output_source_name`
- `output_sid`
- `output_resultfor`
- `output_payload`

Current behavior:

- stores the emitted SmartVA likelihood/output row as JSONB
- preserves per-run emitted output separately from the active projection row
- currently stores likelihood rows only

### `va_smartva_form_runs`

Purpose:

- stores one SmartVA execution batch per form run

Key fields:

- `form_run_id`
- `form_id`
- `project_id`
- `trigger_source`
- `pending_sid_count`
- `outcome`
- `disk_path`
- `run_started_at`
- `run_completed_at`

Current behavior:

- stores the optional on-disk workspace path for raw SmartVA debug artifacts
- groups multiple `va_smartva_runs` created during the same form execution

## Analytics Materialized View

### `va_submission_analytics_mv`

Purpose:

- provides one-row-per-submission analytics data for trends, demographics,
  workflow, SmartVA, and human coding

Key fields:

- project/site/form identifiers
- submission day/week/month buckets
- workflow and sync states
- normalized age fields
- analytics age band
- human initial COD and authoritative final COD
- parsed human ICD prefixes
- SmartVA causes and ICD codes
- `cod_pending_upstream_review` (boolean) — `true` when
  `workflow_state = 'finalized_upstream_changed'`; allows downstream reports to
  distinguish cases with an unresolved upstream change from cleanly-coded cases

KPI policy (Option C):

- `coded_submissions` KPI includes `finalized_upstream_changed` cases alongside
  `coder_finalized`, `reviewer_eligible`, and `reviewer_finalized`
- the dashboard label for these cases is "Data Changed" (not "Revoked")
- `cod_pending_upstream_review` is the flag that lets consumers distinguish them

Current behavior:

- populated by a PostgreSQL materialized view (rebuilt by migration `b1c2d3e4f5a6`)
- refreshed hourly by Celery Beat
- intended for reporting and chart APIs, not operational workflow writes

### `va_submission_upstream_changes`

Purpose:

- durable record of each protected upstream payload change event
- captures a snapshot of what was authoritative at the time of the change so
  the accept/reject decision has full context

Key fields:

- `va_sid` — FK to `va_submissions`
- `previous_payload_version_id` — FK to `va_submission_payload_versions` (was active before the change)
- `pending_payload_version_id` — FK to `va_submission_payload_versions` (new/incoming payload)
- `previous_workflow_state_before` — the submission state at the time of the change
- `previous_final_assessment_id` — FK to `va_final_assessments` (coder COD snapshot)
- `previous_reviewer_final_assessment_id` — nullable FK to
  `va_reviewer_final_assessments` (reviewer COD snapshot, if the submission was
  `reviewer_finalized` at the time); added by migration `aacf89977029`
- `change_status` — `pending` / `accepted` / `kept_current_icd` / `rejected`
- `resolved_by` — user id of the data manager or admin who resolved it
- `resolved_at` — when the resolution occurred

Current behavior:

- created by `record_protected_upstream_change()` in
  `app/services/workflow/upstream_changes.py` whenever a protected submission
  receives a changed ODK payload
- accepted by `dm_accept_upstream_change()` — promotes pending payload to
  active, clears reviewer authority, routes to `smartva_pending`
- resolved by `dm_reject_upstream_change()` — promotes pending payload to
  active, preserves finalized ICD/COD artifacts, restores `workflow_state_before`,
  and records the `kept_current_icd` resolution outcome

### `va_final_cod_authority`

Purpose:

- stores the single authoritative final-COD pointer for each submission

Key fields:

- `va_sid`
- `authoritative_final_assessment_id`
- `authoritative_reviewer_final_assessment_id`
- `authority_source_role`
- `authority_reason`
- `effective_at`
- `updated_by`

Current behavior:

- this table is additive and backfilled from the most recent active
  `va_final_assessments` row during migration
- runtime COD panel rendering now prefers this table when deciding which final
  COD to show as current
- when a recode replacement final COD is submitted, the authority row is moved
  to the replacement final assessment
- when reviewer final COD exists, the authority row may instead point to
  `authoritative_reviewer_final_assessment_id`
- when sync invalidates a submission's finalized COD, the authority row is
  cleared instead of relying only on `va_finassess_status`
- service-level authority resolution now rejects stale coder/reviewer final-COD
  rows whose `payload_version_id` does not match the submission's current
  `active_payload_version_id`

### `va_coding_episodes`

Purpose:

- tracks additive coding episodes such as recode attempts without destroying the
  currently authoritative coder outcome

Key fields:

- `episode_id`
- `va_sid`
- `episode_type`
- `episode_status`
- `started_by`
- `base_final_assessment_id`
- `replacement_final_assessment_id`
- `started_at`
- `completed_at`
- `abandoned_at`

Current behavior:

- currently used for non-destructive `recode` handling
- only one active recode episode is allowed per submission
- starting recode creates an episode but does not deactivate the current
  authoritative final COD
- successful replacement final COD completes the episode and links the
  replacement final assessment
- stale allocation timeout or sync invalidation abandons the active recode
  episode without deleting historical COD rows

### `va_coder_review`

Purpose:

- records coder decision that a submission is not codeable or has an issue

Key fields:

- `va_sid`
- `va_creview_by`
- `va_creview_reason`
- `va_creview_other`
- `va_creview_status`

### `va_data_manager_review`

Purpose:

- records data-manager decision that a submission should be kept out of coder
  allocation

Key fields:

- `va_sid`
- `va_dmreview_by`
- `va_dmreview_reason`
- `va_dmreview_other`
- `va_dmreview_status`

Current behavior:

- one active row is allowed per submission
- this table is distinct from coder-owned Not Codeable records
- an active row drives canonical workflow state
  `not_codeable_by_data_manager`

### `va_reviewer_review`

Purpose:

- legacy reviewer quality/review outcome over a submission

Key fields:

- `va_sid`
- `va_rreview_by`
- review flags and remarks
- `va_rreview`
- `va_rreview_status`

Current behavior:

- this table stores the current legacy reviewer QA/quality-review form
- it does not store reviewer final COD
- it should not be treated as the target reviewer secondary-coding artifact

### `va_reviewer_final_assessments`

Purpose:

- stores the additive reviewer-owned final COD artifact for the new reviewer
  secondary-coding model

Key fields:

- `va_sid`
- `va_rfinassess_by`
- `va_conclusive_cod`
- `va_rfinassess_remark`
- `supersedes_coder_final_assessment_id`
- `va_rfinassess_status`

Current behavior:

- this table now exists in runtime schema
- reviewer final COD rows may coexist with coder final COD rows
- service-level authoritative-final-COD resolution can now prefer reviewer
  final COD from this table
- not all downstream readers have been cut over yet

### `va_narrative_assessments`

Purpose:

- stores coder Narrative Quality Assessment answers for a submission

Key fields:

- `va_sid`
- `payload_version_id`
- `va_nqa_by`
- six scored question fields
- `va_nqa_score`
- `va_nqa_status`
- `demo_expires_at`

Current behavior:

- the table is now payload-version aware
- the current NQA for a coder is the active row whose `payload_version_id`
  matches the submission's `active_payload_version_id`
- payload changes create a new current row on next save unless a protected
  keep-current-ICD decision rebinds the preserved row to the promoted payload
- normal coding leaves `demo_expires_at` null
- demo coding (`vademo_start_coding`) stamps a temporary expiry timestamp
- admin-started demo sessions on ordinary projects use a 6-hour expiry
- `demo_training_enabled` projects use `demo_retention_minutes`, default
  10 minutes

### `va_social_autopsy_analyses`

Purpose:

- stores coder Social Autopsy analysis for a submission as an app-owned workflow artifact

Key fields:

- `va_sid`
- `payload_version_id`
- `va_saa_by`
- `va_saa_remark`
- `va_saa_status`
- `demo_expires_at`

Current behavior:

- the table is now payload-version aware
- the current Social Autopsy row for a coder is the active row whose
  `payload_version_id` matches the submission's `active_payload_version_id`
- normal coding leaves `demo_expires_at` null
- demo coding (`vademo_start_coding`) stamps a temporary expiry timestamp
- admin-started demo sessions on ordinary projects use a 6-hour expiry
- `demo_training_enabled` projects use `demo_retention_minutes`, default
  10 minutes
- one active analysis row is stored per `(va_sid, coder)` at a time; older
  payload versions are kept as inactive history
- selected delay options are normalized into child rows, not flattened into the
  submission JSON
- demo coding stamps a 6-hour expiry timestamp on the parent row so completed
  demo artifacts can be cleaned up automatically

### `va_social_autopsy_analysis_options`

Purpose:

- stores selected Social Autopsy delay-factor options under a parent analysis row

Key fields:

- `va_saa_id`
- `delay_level`
- `option_code`

## Supporting Tables

Other important tables:

- `va_users`
- `va_project_master`
- `va_site_master`
- `va_project_sites`
- `va_user_access_grants`
- `va_usernotes`
- `va_smartva_form_runs`
- `va_smartva_runs`
- `va_smartva_run_outputs`
- `va_smartva_results`
- `va_submissions_auditlog`
- `va_icd_codes`
- `va_forms`
- `va_sites`
- `va_research_projects`

### `map_project_site_odk`

Purpose:

- stores the source-of-truth mapping from a project-site pair to an ODK project and form
- optionally links that mapping to a configured form type

Key fields:

- `project_id`
- `site_id`
- `odk_project_id`
- `odk_form_id`
- `form_type_id`

Current behavior:

- admin project form mapping writes here
- ODK sync now enumerates this table, not `va_forms`, to decide what to sync
- sync then materializes compatibility `va_forms` rows so the legacy workflow stack continues to function

## ODK Connection Tables

### `mas_odk_connections`

Purpose:

- ODK Central connection master; one row per ODK server

Key fields:

- `connection_id` — UUID primary key
- `connection_name` — unique human-readable name for the connection
- `base_url` — base URL of the ODK Central server
- `username_enc` — Fernet-encrypted ciphertext of the username
- `username_salt` — per-row salt used when deriving the encryption key for the username
- `password_enc` — Fernet-encrypted ciphertext of the password
- `password_salt` — per-row salt used when deriving the encryption key for the password
- `status` — active/inactive status (`VaStatuses`)
- `notes` — optional free-text notes
- `created_at`, `updated_at` — timestamps

## Form-Type Mapping Tables

The field-mapping system is scoped by form type under the `mas_*` table family.
These tables are now the source of truth for structural display configuration.

### `mas_form_types`

Purpose:

- registers supported form types such as `WHO_2022_VA` and `WHO_2022_VA_SOCIAL`

Key fields:

- `form_type_id`
- `form_type_code`
- `form_type_name`
- `base_template_path`
- `mapping_version`
- `is_active`

### `mas_category_order`

Legacy compatibility table retained during the category-config cutover. Runtime
navigation and category admin now use `mas_category_display_config` as the
authoritative category table.

Purpose:

- stores category membership and base display order per form type

Key fields:

- `form_type_id`
- `category_code`
- `category_name`
- `display_order`
- `is_active`

### `mas_category_display_config`

Purpose:

- stores category-level display metadata per form type

Key fields:

- `form_type_id`
- `category_code`
- `display_label`
- `nav_label`
- `icon_name`
- `display_order`
- `render_mode`
- `show_to_coder`
- `show_to_reviewer`
- `show_to_site_pi`
- `always_include`
- `is_default_start`
- `is_active`

Current seeded behavior:

- the schema is added by Alembic revision `c7f1d2e3a4b5`
- the migration seeds deterministic rows for `WHO_2022_VA` and `WHO_2022_VA_SOCIAL`
- the current seed count is 14 rows for `WHO_2022_VA` and 15 rows for `WHO_2022_VA_SOCIAL`

### `mas_subcategory_order`

Purpose:

- stores subcategory order within a category for a form type

Key fields:

- `form_type_id`
- `category_code`
- `subcategory_code`
- `subcategory_name`
- `display_order`
- `is_active`

### `mas_field_display_config`

Purpose:

- stores field placement, labels, flags, and order per form type

Key fields:

- `form_type_id`
- `field_id`
- `category_code`
- `subcategory_code`
- `short_label`
- `full_label`
- `summary_label`
- `flip_color`
- `is_info`
- `summary_include`
- `is_pii`
- `display_order`
- `is_active`

### `mas_languages`

Purpose:

- canonical language list for the application
- used by coder profile language selection, submission filtering, and sync normalization

Key fields:

- `language_code` — primary key (e.g. `bangla`, `english`, `hindi`)
- `language_name` — display name (e.g. `Bangla`, `English`, `Hindi`)
- `is_active` — boolean; inactive languages hidden from profile selection

### `map_language_aliases`

Purpose:

- maps raw ODK language values to canonical `mas_languages.language_code`
- lookup table used by `_normalize_language()` during sync

Key fields:

- `alias` — primary key (e.g. `bn`, `bengali`, `Bengali`)
- `language_code` — FK to `mas_languages`

Behavior:

- multiple aliases can map to one canonical code
- alias conflicts across languages are prevented (unique PK)
- unknown ODK values pass through unchanged and appear in admin unmapped alert

### `mas_choice_mappings`

Purpose:

- stores per-form-type choice-value to label translations

Key fields:

- `form_type_id`
- `field_id`
- `choice_value`
- `choice_label`
- `display_order`
- `is_active`

Credential storage:

- credentials are encrypted using Fernet AES-128
- each credential field has its own per-row salt stored alongside it
- a shared pepper is read from the environment at runtime; it is not stored in the database
- multiple projects may share one connection

### `map_project_odk`

Purpose:

- maps one app project to one ODK connection

Key fields:

- `id` — UUID primary key
- `project_id` — String(6) foreign key to the project master, unique constraint enforced
- `connection_id` — UUID foreign key to `mas_odk_connections`

Behavior:

- unique on `project_id` — one project has at most one ODK connection
- a project without a row here falls back to the legacy `odk_config.toml` connection during sync

### `map_project_site_odk`

Purpose:

- maps a project-site pair to a specific ODK Central project ID, form ID, and VA form type

Key fields:

- `id` — UUID primary key
- `project_id` — String(6) foreign key
- `site_id` — String(4) foreign key
- `odk_project_id` — Integer; the numeric project ID on the ODK Central server
- `odk_form_id` — Text; the xmlFormId of the form on ODK Central
- `form_type_id` — UUID nullable foreign key to `mas_form_types`; identifies which VA form type (e.g. `WHO_2022_VA`, `WHO_2022_VA_SOCIAL`) this site uses for field display and rendering
- `created_at`, `updated_at` — timestamps

Behavior:

- unique on `(project_id, site_id)` — one ODK form per project-site combination
- the ODK connection used for this mapping is derived via `map_project_odk` and is not stored here directly
- `form_type_id` is optional but strongly recommended; if absent, rendering falls back to the hardcoded default `WHO_2022_VA`

### `va_sync_runs`

Purpose:

- records every ODK sync run — start time, outcome, and submission-level metrics

Key fields:

- `sync_run_id` — UUID primary key
- `triggered_by` — `"scheduled"` or `"manual"`
- `triggered_user_id` — nullable FK to `va_users.user_id` (set for manual runs)
- `started_at` — indexed timestamp when the run began
- `finished_at` — null while the run is in progress
- `status` — `"running"` / `"success"` / `"error"`
- `records_added`, `records_updated` — submission counts from the completed run
- `error_message` — first 2000 chars of the exception on failure

Current behavior:

- written by the `run_odk_sync` Celery task in `app/tasks/sync_tasks.py`
- a `"running"` row is committed before sync begins so the admin dashboard can display live status
- stale `"running"` rows older than 2 hours are marked `"error"` on worker restart

## Key Current-State Observations

- sites are modeled as project-owned
- forms are overloaded with multiple responsibilities
- submissions are keyed to synthetic app form identity
- legacy runtime permissions still center on `va_users.permission`
- explicit auth foundation tables now exist additively in `va_project_master`, `va_site_master`, `va_project_sites`, and `va_user_access_grants`, but runtime authorization has not cut over yet
- ODK identifiers are stored per app form
- ODK connection credentials are now stored encrypted in `mas_odk_connections` rather than in a flat TOML file
- per-site ODK project, form, and VA form type mapping is now managed via `map_project_site_odk`
- the current schema is suitable for one-project-first operation, not generalized multi-project reuse
