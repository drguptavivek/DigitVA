---
title: Current Data Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-12
---

# Current Data Model

## Summary

The current model is centered on:

- `Project`
- `Site`
- `Form`
- `Submission`

with workflow state attached to submissions.

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

Current role:

- top-level project master, but effectively used in a one-project deployment model

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
- `va_instance_name`
- `va_uniqueid_real`
- `va_uniqueid_masked`
- `va_consent`
- `va_narration_language`
- `va_deceased_age`
- `va_deceased_gender`
- `va_data`
- `va_summary`
- `va_catcount`
- `va_category_list`

Current behavior:

- `va_form_id` points to `va_forms.form_id`
- `va_data` holds the processed ODK row as JSONB
- additional structured and derived fields are extracted for workflow and UI use

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
- `va_finassess_by`
- `va_conclusive_cod`
- `va_finassess_remark`
- `va_finassess_status`

### `va_coder_review`

Purpose:

- records coder decision that a submission is not codeable or has an issue

Key fields:

- `va_sid`
- `va_creview_by`
- `va_creview_reason`
- `va_creview_other`
- `va_creview_status`

### `va_reviewer_review`

Purpose:

- reviewer quality/review outcome over a submission

Key fields:

- `va_sid`
- `va_rreview_by`
- review flags and remarks
- `va_rreview`
- `va_rreview_status`

## Supporting Tables

Other important tables:

- `va_users`
- `va_project_master`
- `va_site_master`
- `va_project_sites`
- `va_user_access_grants`
- `va_usernotes`
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
