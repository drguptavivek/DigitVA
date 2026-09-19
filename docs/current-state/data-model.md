---
title: Current Data Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-19
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
- `reviewer_social_autopsy_enabled`
- `coding_intake_mode`
- `demo_training_enabled`
- `demo_retention_minutes`

Current role:

- top-level project master, but effectively used in a one-project deployment model
- also stores project-level workflow toggles such as Narrative QA enablement,
  coder/reviewer Social Autopsy analysis enablement, and coder intake mode
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

## COD Reporting Master Tables

### `mas_cod_bucket_schemes`

Purpose:

- stores versioned COD reporting schemes such as `SRS India` and `CMEA10`

### `mas_cod_bucket_scheme_age_bands`

Purpose:

- stores age-band metadata for a COD reporting scheme

Key fields:

- `scheme_id`
- `age_scope`
- `age_label`
- `min_age_value`
- `min_age_unit`
- `max_age_value`
- `max_age_unit`
- `level_count`
- `sort_order`

Current behavior:

- lower bound is inclusive
- upper bound is exclusive
- all age bands persist explicit min/max bounds; no `NULL` open-ended ranges
- built-in open-ended scopes currently use `120 years` as the explicit upper cap
- unit normalization for reporting uses:
  - `days = 1`
  - `months = 365 / 12`
  - `years = 365`

### `mas_cod_bucket_nodes`

Purpose:

- stores hierarchy nodes inside a COD reporting scheme

Current behavior:

- supports variable depth by `scheme_id + age_scope`
- node types currently used are:
  - `category`
  - `subcategory`
  - `field`

### `map_icd_cod_buckets`

Purpose:

- maps an ICD code to one reporting leaf within a scheme and age scope

Current behavior:

- one ICD code can map to only one leaf per `scheme_id + age_scope`

## Organization Master Tables

Health-system projects describe their hierarchy with these per-project tables
(policy: `docs/policy/organization-model.md`; plan:
`docs/planning/health-system-organization-model-plan.md`). Projects without
rows here keep the Project > Site > Form model.

### `mas_org_level`

- one row per level of a project's tree: `level_code`, `level_name`, `depth`
  (1 = top), `is_optional`, `is_active`
- unique on (`project_id`, `level_code`) and (`project_id`, `depth`)
- the ODK form field for a level is `org_<level_code>_code`

### `mas_org_unit`

- one row per unit: `unit_code` (unique per project), `unit_name`,
  `org_level_id`, `parent_org_unit_id`, `path` (PostgreSQL `ltree` of unit
  codes, GiST-indexed), `address`, `phone`, `latitude`, `longitude`,
  `google_maps_url`, `remarks`, `is_active`
- subtree queries use `path <@ :ancestor_path`

### `mas_cadre`

- per-project cadres: `cadre_code` (unique per project), `cadre_name`, `is_active`

### `map_org_level_cadre`

- which cadres exist at a level: `org_level_id`, `cadre_id`,
  `can_fill_va_form`, `can_code_va_form`, `is_active`; unique on (level, cadre)

### `mas_org_unit_worker`

- people attached to a unit: `worker_code` (unique per project), `worker_name`,
  `org_unit_id`, `cadre_id`, `phone`, optional `user_id` (`va_users`), `remarks`,
  `is_active`
- name and phone are personal data

### Unit-scoped access grants

- `va_user_access_grants` accepts `scope_type = 'org_unit'` with
  `org_unit_id` (FK `mas_org_unit`) and an optional descriptive `cadre_id`
  (FK `mas_cadre`)
- a unit grant leaves `project_id` and `project_site_id` empty; the grant's
  project is the unit's project, resolved in queries through the unit
- the grant covers the unit's whole subtree (`path <@ grant unit path`)
- check constraints: the scope shape, the role/scope pairs (`site_pi`,
  `collaborator`, `coder`, `coding_tester`, `reviewer`, `data_manager` may use
  `org_unit`), and `cadre_id` only on unit grants
- partial unique index `uq_va_user_access_grants_org_unit` on
  (`user_id`, `role`, `org_unit_id`); lookup index on
  (`org_unit_id`, `role`, `grant_status`)
- resolution lives in `app/services/org_grant_service.py`; coding and reviewer
  enforcement still runs off `va_forms`, so a unit grant does not yet change
  what a coder may open

### Submission routing to units

- `map_project_site_odk.org_unit_id` (nullable, FK `mas_org_unit`): the
  fallback unit for submissions of that ODK form whose payload carries no
  usable unit code
- `va_submissions.org_unit_id` (nullable, indexed, FK `mas_org_unit`): the
  unit a death is attributed to
- `va_submissions.org_unit_resolution`: `form_field`, `mapping_fallback` or
  `manual`, constrained to those values and required whenever `org_unit_id` is
  set (and forbidden when it is not)
- `va_submissions.org_unit_pinned_by` / `org_unit_pinned_at`: who pinned the
  unit by hand and when; a check constraint allows them only alongside
  `org_unit_resolution = 'manual'`
- index on (`org_unit_id`, `org_unit_resolution`) for the unrouted queue
- rules in `app/services/org_unit_routing_service.py`, applied by ODK sync and
  by web intake

### Several ODK forms per project-site

- `map_project_site_odk` is unique on
  (`project_id`, `site_id`, `odk_project_id`, `odk_form_id`), not on
  (`project_id`, `site_id`): one DigitVA project accepts submissions from
  several ODK Central forms over one connection
- each mapping materializes its **own** `va_forms` row; the two are matched on
  project, site, ODK project and ODK form. `va_forms.odk_project_id` is text
  while the mapping's is an integer, so joins compare them as text
- the reverse rule still holds and is enforced in
  `app/services/odk_form_mapping_service.py`: one ODK form belongs to one
  project-site per connection
- `_next_form_id` already allocated sequential ids per project-site
  (`PRJ01ST0101`, `…02`), so several forms per pair need no identity change

### Project coding scope

- `va_project_master.coding_scope_level_id` (nullable, FK `mas_org_level`):
  the level within which a death may be coded; NULL means no unit-based scope
- `va_project_master.above_scope_coding_mode`: `code_any` or `view_only`
  (check-constrained), governing coders granted above that level
- a project with a scope level must use `pick_and_choose` coding intake

Migrations: `c8d2e4f6a1b3` (additive; enables the `ltree` extension),
`d9e3f5a7b2c4` (additive; adds the `org_unit` scope value and the two grant
columns), `c1d4e7f9a3b6` (additive; adds the routing columns),
`e2a5c8b1d7f3` (widens the mapping uniqueness constraint),
`f7b2d4e6a8c9` (additive; adds the project coding-scope columns).

## ICD Reference Master Table

### `mas_icd10_2019_2`

Purpose:

- stores the ICD-10 2019 hierarchy as denormalized master reference data for
  coding and future policy curation

Key fields:

- `code`
- `title`
- `node_type`
- `semantic_level`
- `parent_code`
- `chapter_code`
- `block_code`
- `three_character_code`
- `sort_order`
- `is_coding_selectable`
- `sex_selectable`
- `age_group_selectable`
- `is_active`

Current behavior:

- one row per ICD hierarchy node
- includes chapters, blocks, three-character categories, and detailed dotted
  codes
- includes modifier-derived detailed rows expanded from the WHO ClaML XML, such
  as `V01.1`, `V10.4`, and `E10.0`
- fresh migration creation seeds the table from the checked-in ICD hierarchy CSV
- coder ICD search now reads from this table for selectable three-character and
  detailed-code lookup
- coding-time age policy supports `all`, `neonate`, `infant`, `child`, and
  `adult`; submission age is classified as `<28 days`, `28-<365 days`,
  `365 days-<12 years`, and `>=12 years`
- preserves local policy flags in the same table
- import is idempotent:
  - existing rows are updated by `code`
  - newly introduced rows are inserted
  - source-missing rows are marked inactive rather than deleted

### `mas_icd11_mms`

Purpose:

- stores the WHO ICD-11 MMS linearization (a given `release`, e.g. `2026-01`)
  as master reference data, mirroring the `mas_icd10_2019_2` policy pattern.
  See docs/policy/icd11-reference-catalog.md.

Key fields:

- `id` (surrogate uuid primary key)
- `release`, `linearization_uri` (unique together — the stable key per release)
- `foundation_uri` (nullable — residual categories have none)
- `code` (nullable — chapters and blocks have none), `block_id`
- `title` (WHO's `- ` depth prefixes stripped)
- `class_kind` (`chapter` | `block` | `category`), `depth_in_kind`, `chapter_no`
- `is_residual`, `is_leaf`, `primary_tabulation` (informational only — WHO
  leaves its meaning undefined), `coding_note`, `sort_order`
- `parent_foundation_uri` (from the export's `Parent` column),
  `parent_linearization_uri` (resolved on import)
- `is_coding_selectable`, `sex_selectable`, `age_group_selectable`,
  `policy_status`, `restriction_note` (DigitVA-local policy fields, same
  semantics as `mas_icd10_2019_2`)
- `is_active`, `source_version`, `source_path`

Current behavior (phases 1-2 of
docs/planning/icd11-coding-screen-integration-plan.md):

- one row per linearization entity in the frozen WHO Simple Tabulation export
  (`docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-2026-01-base-2026-09-16/`)
- fresh migration creation seeds the table from the checked-in generated CSV
  (`resource/icd11_mms_2026_01_hierarchy.csv`)
- import (`app/services/icd11_mms_service.py::import_icd11_mms_from_export`,
  `flask icd11 import`) is idempotent and streamed/batched, upserting on
  `(release, linearization_uri)`; source-missing rows are marked inactive,
  never deleted; policy columns are preserved on rerun unless
  `apply_policy_columns` is set
- read-only admin browser at `/admin/panels/icd11-browser`
  (`app/routes/admin_icd11.py`); local policy curation for phases 1-2 happens
  through `flask icd11 policy-export`/`policy-import`, not the panel
- `map_project_site_odk.icd_classification` (`icd10` | `icd11`, default
  `icd10`) selects which catalog a project-site's form uses; resolved for a
  submission by `app/services/icd_coding_value.py::get_icd_classification_for_submission`
- ICD-11 coding-screen search, validation, and per-code allowability policy
  (phase 5 of the plan) are not implemented yet

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

Deprecated as of 2026-04-20.

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
- primary ICD lookup behavior has moved to `mas_icd10_2019_2`
- remaining `va_icd_codes` usage is legacy compatibility and source-workbook
  support, not the primary runtime ICD catalog

### `mas_cod_bucket_schemes`

Purpose:

- stores versioned reporting taxonomies for ICD bucket aggregation

Key fields:

- `scheme_code`
- `scheme_name`
- `mapping_version`
- `source_path`
- `is_active`

Current behavior:

- separate from submission COD data
- examples include `SRS India` and `CMEA10`

### `mas_cod_bucket_nodes`

Purpose:

- stores the hierarchy nodes inside a reporting scheme

Key fields:

- `scheme_id`
- `age_scope`
- `node_type`
- `parent_node_id`
- `node_code`
- `node_label`

Current behavior:

- supports variable hierarchy depth
- supports age-scoped trees, used by `SRS India`
- supports flat schemes, used by `CMEA10`

### `map_icd_cod_buckets`

Purpose:

- maps an ICD code and optional age scope to a reporting leaf node

Key fields:

- `scheme_id`
- `age_scope`
- `icd_code`
- `node_id`
- `source_sheet`
- `source_row_number`

Current behavior:

- leaves coded submissions unchanged
- drives reporting-only COD bucket aggregation

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
- `archive_state` (`local` | `archived` | `failed` | `absent`, NOT NULL,
  default `local`, indexed)
- `archive_key_prefix`
- `archived_at`
- `archive_error_code`
- `archive_file_count`
- `archive_bytes`

Current behavior:

- stores the on-disk workspace path for raw SmartVA debug artifacts, relative to
  `APP_SMARTVA_RUNS`
- groups multiple `va_smartva_runs` created during the same form execution
- the archive columns record where that workspace lives now: with
  `ATTACHMENT_STORE=s3` it is copied to the DigitVA bucket under
  `smartva_runs/{project_id}/{form_id}/{form_run_id}/`, verified, and then
  removed from the VM — at which point `disk_path` becomes NULL and
  `archive_key_prefix` holds the store-relative prefix
- `archive_error_code` is a short category only (`upload_failed`,
  `verify_mismatch`, `store_unavailable`, `walk_failed`,
  `local_delete_failed`) — never a path, a key or a submission identifier
- migration `d3b8f1e40a72`; policy baseline
  [SmartVA Generation Policy](../policy/smartva-generation-policy.md)

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
- `va_project_master` — also carries `project_target_completion_date` (DATE, nullable), the
  admin-set target the DM burndown KPI projects against
  (`app/routes/api/dm_kpi/dm_kpi_burndown.py`), and the four web intake form
  options served by `GET /api/v1/organization/<project_id>/form-options`
  (migration `f2a9c4d7e1b3`): `web_intake_default_locale` (String(16), NOT
  NULL, default `'en'`), `web_intake_available_locales` (JSONB, nullable —
  NULL means every active language), `web_intake_narration_languages` (JSONB,
  nullable — NULL means none offered) and `web_intake_show_guidance` (Boolean,
  NOT NULL, default false). Migration `c3e8b5a1f4d2` adds the web
  questionnaire and its two extension settings:
  `web_intake_form_type_id` (UUID, nullable, FK
  `fk_va_project_master_web_intake_form_type` -> `mas_form_types.form_type_id`
  — NULL means `WHO_2022_VA`), `web_intake_intake_note` (Text, nullable —
  NULL means the system default welcome note, `''` means no welcome screen)
  and `web_intake_death_summary_enabled` (Boolean, NOT NULL, default true).
  Policy: `docs/policy/va-web-form-options.md`,
  `docs/policy/va-form-project-configuration.md`
- `va_site_master`
- `va_project_sites`
- `va_user_access_grants` — see [Unit-scoped access grants](#unit-scoped-access-grants)
  for the `org_unit` scope columns. Also carries `created_by_user_id` (UUID, nullable,
  FK `fk_va_user_access_grants_created_by` -> `va_users.user_id`). Nothing reads or writes it
  today; DM-created users are attributed through `va_users.other["created_by_user_id"]`
  instead, so the column is a drop candidate rather than live state.
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

### `va_submission_attachments`

Purpose:

- one row per (`va_sid`, `filename`) ODK submission attachment
- ETag cache for conditional GET, plus the local blob's opaque `storage_name`
- readiness state for the Central-backed attachment work

Key fields:

- `va_sid`, `filename` — composite primary key
- `local_path` — actual path on disk; differs from `filename` for `.amr`, which is
  stored as its `.mp3` derivative
- `mime_type` — copied from upstream, not authoritative (may be the derivative's
  type for AMR rows)
- `etag`, `last_downloaded_at`, `exists_on_odk`
- `storage_name` — opaque serving token (unique where not null)

Source/derivative state (added by migration `b7e4c2a91d38`, Phase 2 of the
[Central attachment plan](../planning/s3-attachment-plan.md)). Vocabularies are
constants in `app/services/attachment_service.py`; all timestamps are timezone-aware:

| Column | Type | Meaning |
|---|---|---|
| `source_state` | VARCHAR(16) NOT NULL, default `unknown` | `unknown`, `listed`, `available`, `missing`, `retired`, `error` |
| `source_verified_at` | TIMESTAMPTZ | last observed Central content response |
| `source_error_code` | VARCHAR(32) | `not_found`, `auth`, `throttled`, `transient`, `invalid_redirect`, `unknown` — category only, never free text |
| `source_mime_type` | VARCHAR(64) | validated MIME of the **original**; `mime_type` is not repurposed |
| `derivative_state` | VARCHAR(16) | audio only: `pending`, `ready`, `stale`, `error`; NULL for non-audio rows |
| `derivative_mime_type` | VARCHAR(64) | e.g. `audio/mpeg` |
| `derivative_source_validator` | VARCHAR(128) | opaque source ETag the current MP3 was built from |
| `derivative_verified_at` | TIMESTAMPTZ | last derivative verification |
| `derivative_error_code` | VARCHAR(32) | e.g. `conversion_failed` |
| `local_fallback_state` | VARCHAR(16) NOT NULL, default `present` | `present`, `retained` (archival copy of a retired submission — never deleted), `quarantined`, `absent` |

Store location (added by migration `a4f1c07b62d9`):

| Column | Type | Meaning |
|---|---|---|
| `store_state` | VARCHAR(16) NOT NULL, default `local` | which store holds the blob: `local` (a file under `APP_DATA/<form_id>/media/`), `s3` (an object in the DigitVA bucket; `local_path` is NULL for these rows), `absent` (not stored anywhere yet) |

Indexes:

- `ix_va_submission_attachments_sid_odk` — partial, `exists_on_odk IS TRUE`
- `ix_va_submission_attachments_storage_name` — unique, partial, `storage_name IS NOT NULL`
- `ix_va_submission_attachments_source_state` — request-path readiness reads
- `ix_va_submission_attachments_derivative_state` — partial, `derivative_state IS NOT NULL`,
  for repair candidate selection over the audio rows only
- `ix_va_submission_attachments_store_state` — cutover tool and integrity check
  select rows by which store holds their object

Current behavior:

- sync writes `source_state='available'` with the observed time and the original's
  validated MIME on a successful download, `'missing'` when ODK no longer lists the
  file, and the AMR derivative columns (including the ETag it was built from) when
  an MP3 is produced; a failed conversion records `derivative_state='error'`,
  `derivative_error_code='conversion_failed'` and leaves the previous blob alone
- with `ATTACHMENT_STORE=s3`, sync uploads the blob and writes `store_state='s3'`,
  `local_path=NULL`, `local_fallback_state='absent'`; with the local store it keeps
  writing `store_state='local'` and the file path exactly as before
- bulk presence (`present_attachment_files_by_submission()`) resolves an `s3` row
  from `store_state` alone and a `local` row from disk; it never probes the bucket
  per row. Object-level truth comes from
  `scripts/check_attachment_integrity.py --store s3`

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
- `base_instrument_code` — String(32), nullable (migration `c3e8b5a1f4d2`,
  backfilled `WHO_2022_VA` for every `WHO_2022_VA%` code): the standard
  instrument this form type layers on. Read by `instrument_code_for()` to tell
  the web form which bundled questionnaire to render; NULL means none is
  bundled. Policy: `docs/policy/new-form-type-onboarding.md`
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

### `va_db_backups`

Purpose:

- records every database dump — where it went, how big it was, and its sha256

Key fields:

- `backup_id` — UUID primary key
- `started_at` — timestamptz, indexed `DESC` (`ix_va_db_backups_started_at`)
- `completed_at` — null while the dump is in progress
- `triggered_by` — `"scheduled"` / `"manual"` / `"cli"`
- `triggered_user_id` — nullable FK to `va_users.user_id` (set for admin-triggered runs)
- `status` — `"running"` / `"success"` / `"failed"` / `"pruned"`, indexed (`ix_va_db_backups_status`)
- `store` — `"local"` or `"s3"`
- `object_key` — the bucket key (or the file name on the local store); the only
  identifier a dump has outside the store
- `size_bytes`, `sha256` — recorded on success; the sha256 is what a restore verifies against
- `error_code` — short failure category (`pg_dump_failed`, `upload_failed`,
  `verify_mismatch`, `dump_too_large`, …), never a message from `pg_dump` or the transport
- `pruned_at` — set when retention removed the object

Current behavior:

- written by `app/services/db_backup_service.py`, driven by the `run_db_backup`
  Celery task, the `flask backups` CLI, and the admin Database backups panel
- a `"running"` row is committed before `pg_dump` starts, so an interrupted run
  leaves evidence rather than nothing
- `DB_BACKUP_KEEP_DAILY` retention flips a `"success"` row to `"pruned"` when its
  object is deleted; the row is kept as history
- this table is the only dump history on the VM — see [backup.md](backup.md)

## Schema Drift Guard

The models must describe the live schema exactly — indexes, constraint names, foreign-key
names and `ondelete` included — so that autogenerate has nothing to say.

- **Naming convention.** `db` is constructed with a `MetaData(naming_convention=...)` in
  `app/__init__.py`, so constraints the models leave unnamed get deterministic names. The
  `uq` key is `%(table_name)s_%(column_0_name)s_key`, PostgreSQL's own default, rather than
  the Alembic-standard `uq_...`: Alembic applies the convention to tables built by
  `op.create_table` too, so the standard form would retroactively rename constraints that
  existing migrations already created under the PostgreSQL name.
- **Externally-owned tables.** `app/schema_filters.include_object` hides the `celery_*`
  scheduler tables and the Flask-Session `va_sessions` table from the comparison.
  `migrations/env.py` installs it for both the offline and online contexts.
- **Check before committing a model change.**

  ```bash
  docker compose exec -T minerva_app_service uv run flask db check
  ```

  It is read-only and must print `No new upgrade operations detected.`
- **Automated guard.** `tests/migrations/test_schema_drift.py` creates a throwaway database,
  builds it with `flask db upgrade` alone (never `create_all()`), and asserts that
  `compare_metadata` against `db.metadata` returns nothing. The rest of the suite builds its
  schema with `create_all()` and so cannot see this class of drift.

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
