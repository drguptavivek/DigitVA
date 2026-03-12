---
title: "Plan: Config-Driven Category Rendering"
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-03-12
---

# Plan: Config-Driven Category Rendering

## Goal

Replace the current hardcoded submission category rendering path with a form-type-aware,
configuration-driven renderer for submission-data panels.

This plan covers:

- left-nav category generation
- category route resolution
- category/subcategory/field ordering
- generic rendering of mapped submission fields
- category- and field-level render modes

This plan does **not** attempt to genericize workflow or computed-result panels such as:

- SmartVA display
- initial ICD / COD entry
- final ICD / COD entry
- coder review / reviewer review forms
- narrative quality assessment forms
- notes and other app-owned workflow UI

Those remain explicit application panels.

## Problem Statement

The current category rendering system is split across multiple hardcoded layers:

- [`app/routes/va_api.py`](../../app/routes/va_api.py) uses a hardcoded `va_renderforall`
  list and hardcodes `WHO_2022_VA`
- [`app/templates/va_frontpages/va_coding.html`](../../app/templates/va_frontpages/va_coding.html)
  hardcodes left-nav buttons and labels
- coder rendering still uses the static dict in
  [`app/utils/va_mapping/va_mapping_02_fieldcoder.py`](../../app/utils/va_mapping/va_mapping_02_fieldcoder.py)
- category display is implemented by per-category partials under
  [`app/templates/va_formcategory_partials/`](../../app/templates/va_formcategory_partials)

This is already in tension with the current data model, because category, subcategory,
field placement, and ordering are now largely represented in database config.

As a result:

- new form types require code changes
- new categories require code changes
- nav, preprocessing, and render routing can drift
- category-specific templates duplicate DB structure
- coder and site-PI rendering paths are inconsistent

## Current Assets We Can Reuse

The repo already has the core structural metadata needed for a generic renderer:

- `MasCategoryOrder`
  - category code
  - display order
- `MasSubcategoryOrder`
  - subcategory code
  - display order
- `MasFieldDisplayConfig`
  - category placement
  - subcategory placement
  - field display order
  - `flip_color`
  - `is_info`
  - `is_pii`
  - `summary_include`

The field mapping service already produces ordered structures from DB config.

This means the remaining work is not category structure itself. The missing layer is
render metadata and runtime routing.

## Scope Boundary

### In Scope

Submission-derived, read-only category panels backed by `va_submission.va_data`:

- `vainterviewdetails`
- `vademographicdetails`
- `vaneonatalperioddetails`
- `vainjuriesdetails`
- `vahealthhistorydetails`
- `vageneralsymptoms`
- `varespiratorycardiacsymptoms`
- `vaabdominalsymptoms`
- `vaneurologicalsymptoms`
- `vaskinmucosalsymptoms`
- `vaneonatalfeedingsymptoms`
- `vamaternalsymptoms`
- `vahealthserviceutilisation`
- `vanarrationanddocuments`
- future categories such as `social_autopsy`

### Out of Scope

Explicit application or computed-result panels:

- SmartVA result display
- initial assessment panels
- final assessment panels
- coder review / reviewer review panels
- narrative quality forms
- note entry / note display panels

## Target Architecture

The coding screen should be split into two panel classes.

### 1. Config-Driven Submission Categories

These panels:

- render only submission field data
- derive structure from DB config
- are form-type aware
- are role aware
- are rendered by a generic engine

### 2. Explicit Workflow Panels

These panels:

- are backed by app-owned models and forms
- keep explicit routes, templates, and WTForms
- are not part of the generic category engine

## Design Principles

1. Do not branch the generic renderer on category code.
2. Branch only on configured render mode.
3. Keep workflow panels separate from submission-field rendering.
4. Preserve backward compatibility during migration.
5. Prefer staged cutover over deleting all partials at once.
6. Keep preprocessing, left-nav behavior, and render routing aligned on the same config source.

## Required Metadata Model

The current DB model already handles structure and ordering. To support generic
rendering, we need to add display metadata.

### Category-Level Metadata

Each category needs:

- `category_code`
- display label
- nav label
- icon
- display order
- render mode
- role visibility flags
  - visible to coder
  - visible to reviewer
  - visible to site PI
- optional always-include flag
- optional default-open / preferred-start flag

This can be implemented either by extending `MasCategoryOrder` or by introducing a
dedicated category display config table keyed by form type and category code.

Recommendation:

- introduce a dedicated category display config table rather than overloading
  `MasCategoryOrder` further

Reason:

- `MasCategoryOrder` currently reads as an ordering table
- render mode, icon, labels, and role visibility are display metadata, not just order
- a dedicated table will be easier to reason about, test, and evolve

Suggested shape:

- `mas_category_display_config`
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

### Subcategory-Level Metadata

Current subcategory order already exists.

Needed addition:

- display label
- optional render mode override

Suggested shape:

- extend current subcategory config or add:
  - `display_label`
  - optional `render_mode`

This is lower priority than category metadata. A generic renderer can initially derive
section headers from existing subcategory code/name mapping if labels already exist in
the admin layer.

### Field-Level Metadata

Current field flags are already valuable:

- `flip_color`
- `is_info`
- `is_pii`
- `summary_include`

The missing field display concept is `render_type`.

Suggested additions to `MasFieldDisplayConfig`:

- `render_type`
- optional role visibility flags if coder/reviewer/site-PI should differ by field

Suggested `render_type` values:

- `text`
- `choice`
- `date`
- `datetime`
- `multiselect`
- `audio`
- `image`
- `document_image`
- `long_text`

The current system can infer some of these from field IDs and existing helper lists, but
that logic should be moved toward explicit config over time.

## Render Mode Catalog

The generic renderer needs a small, explicit catalog of render modes.

### Category Render Modes

#### `table_sections`

Default mode for most current categories.

Behavior:

- render each subcategory as a titled section
- render fields in query/response table form
- apply standard flip/info/pii formatting

Expected first-wave categories:

- `vademographicdetails`
- `vaneonatalperioddetails`
- `vainjuriesdetails`
- `vageneralsymptoms`
- `varespiratorycardiacsymptoms`
- `vaneurologicalsymptoms`
- `vaskinmucosalsymptoms`
- `vaneonatalfeedingsymptoms`
- `vamaternalsymptoms`
- `vahealthserviceutilisation`
- `vainterviewdetails`

#### `health_history_summary`

Needed for `vahealthhistorydetails`.

Behavior:

- identify binary `Yes` / `No` responses in the configured health-history subcategory
- render positive diagnoses as a summary card
- render absent diagnoses as a summary card
- render non-binary leftovers as a detail table
- render other subcategories, such as `neonate`, as normal tables

Important requirement:

- this must be driven by mode config, not by hardcoding `vahealthhistorydetails`

#### `attachments`

Needed for `vanarrationanddocuments`.

Behavior:

- render text rows normally
- render audio as an audio player
- render narrative image as an image display
- render image collections as galleries or carousels

This may later split into:

- `narrative_documents`
- `image_gallery`

But one initial attachments-oriented mode is sufficient if implemented cleanly.

### Field Render Types

Field render types should decide how a value is transformed before display:

- `text`: plain value
- `choice`: mapped label
- `date`: formatted date
- `datetime`: formatted datetime
- `multiselect`: expanded multi-select labels
- `audio`: media URL + player
- `image`: media URL + image renderer
- `document_image`: media URL + gallery renderer
- `long_text`: narrative/paragraph display

## Target Runtime Flow

### Current End State

1. resolve submission and form type
2. load category display config for that form type and current role
3. load field/subcategory/category placement config for that form type and role
4. compute visible categories from surviving data plus category `always_include`
5. render left nav from category config
6. render generic category panel from the selected category's render mode
7. keep previous/next traversal aligned with the same computed visible category list

### Important Behavioral Rule

The same config source must govern:

- which categories exist
- category order
- nav visibility
- render eligibility
- previous/next traversal

This replaces the current split between:

- hardcoded nav
- hardcoded `va_renderforall`
- stored `va_category_list`
- render-time recalculation

## Proposed Service Layer Changes

Introduce a category rendering service that separates configuration loading from value
processing.

Suggested responsibilities:

### `CategoryRenderingService`

- resolve form type for a submission
- load category display config for a role
- load ordered category/subcategory/field mappings
- compute visible categories from submission data
- build the render context for nav and content

Suggested outputs:

- ordered visible category list
- category metadata
- selected category render payload
- previous / next category codes

### `FieldValueRenderingService`

- apply the existing filter rules
- handle choice, date, datetime, multiselect formatting
- handle attachment URL resolution
- apply PII masking
- normalize output shape for the template layer

This allows the template layer to stay small.

## Schema / Migration Plan

### Phase A: Additive Schema

Add new metadata without breaking current behavior.

1. Add category display config table
2. Add category role visibility flags
3. Add category render mode
4. Add field `render_type`
5. Optionally add field role visibility flags if needed

Migration requirements:

- additive only
- no destructive rewrite of existing mapping rows
- seed sensible defaults for existing WHO 2022 VA categories

### Phase B: Seed / Backfill

Populate initial config for current form types.

Seed defaults:

- category labels and nav labels from current UI
- icons from current hardcoded nav
- `table_sections` for standard categories
- `health_history_summary` for `vahealthhistorydetails`
- `attachments` for `vanarrationanddocuments`
- current role visibility semantics
  - `vainterviewdetails`: site-PI only
  - standard categories: visible to coder/reviewer/site PI as currently intended
  - `vanarrationanddocuments`: visible wherever it is today

Field render types initial backfill:

- derive from current helper lists and attachment field IDs
- keep fallback inference in code during transition

## Implementation Phases

### Phase 1: Form-Type-Aware Runtime Foundation

Objective:

- stop hardcoding `WHO_2022_VA`
- resolve form type from the submission everywhere relevant

Tasks:

- make category rendering route form-type aware
- make preprocess form-type aware
- make nav context form-type aware

Outcome:

- the runtime can serve different category configs per form type

### Phase 2: DB-Driven Category Metadata

Objective:

- move category existence/order/labels/icons/visibility into config

Tasks:

- add category display config table
- seed current WHO 2022 VA category metadata
- add service-layer loaders
- stop relying on hardcoded nav button definitions

Outcome:

- nav and route eligibility come from DB config

### Phase 3: Generic Renderer For `table_sections`

Objective:

- replace the simplest category partials first

Tasks:

- build generic category template
- build generic subcategory section include
- build generic field row include
- apply existing flip/info formatting
- preserve current previous/next footer behavior

First-wave categories:

- `vademographicdetails`
- `vaneonatalperioddetails`
- `vainjuriesdetails`
- `vageneralsymptoms`
- `varespiratorycardiacsymptoms`
- `vaneurologicalsymptoms`
- `vaskinmucosalsymptoms`
- `vaneonatalfeedingsymptoms`
- `vamaternalsymptoms`
- `vahealthserviceutilisation`
- `vainterviewdetails`

Outcome:

- most category partials can be retired without changing workflow panels

### Phase 4: Special Render Modes

Objective:

- migrate the exception categories

Tasks:

- implement `health_history_summary`
- implement `attachments`
- migrate:
  - `vahealthhistorydetails`
  - `vanarrationanddocuments`
  - `vaabdominalsymptoms` mismatch cleanup if needed

Outcome:

- all submission-data categories are served by the generic render engine

### Phase 5: Preprocess / Visibility Alignment

Objective:

- remove drift between stored nav visibility and render-time content

Options:

1. keep stored `va_category_list`, but regenerate it from the same config-driven service
2. stop storing nav visibility and compute it at runtime

Recommendation:

- keep `va_category_list` initially for backward compatibility and neighbor traversal
- regenerate it from the same service used by runtime rendering

This is the smaller cutover.

Outcome:

- nav visibility, traversal, and render eligibility align

### Phase 6: Remove Legacy Static Rendering

Objective:

- delete old category-specific static structures once parity is proven

Tasks:

- remove hardcoded `va_renderforall`
- remove hardcoded nav buttons
- remove `va_mapping_02_fieldcoder.py` from category rendering path
- delete retired category partials

Outcome:

- the submission category system is fully config-driven

## Category Migration Order

### Low-Risk First

- `vademographicdetails`
- `vaneonatalperioddetails`
- `vainjuriesdetails`
- `vageneralsymptoms`
- `varespiratorycardiacsymptoms`
- `vaneurologicalsymptoms`
- `vaskinmucosalsymptoms`
- `vaneonatalfeedingsymptoms`
- `vamaternalsymptoms`
- `vahealthserviceutilisation`

These are mostly straightforward table sections.

### Medium-Risk

- `vainterviewdetails`
- `vaabdominalsymptoms`

Reasons:

- `vainterviewdetails` is role-gated
- `vaabdominalsymptoms` currently has a mapping/partial mismatch (`bleeding`)

### High-Risk / Special Mode

- `vahealthhistorydetails`
- `vanarrationanddocuments`

Reasons:

- custom summary-card logic
- media and gallery rendering

## Policy Decisions Needed

Before implementation, these policy points should be fixed explicitly:

1. Is category visibility stored (`va_category_list`) or runtime-derived?
2. Is role visibility controlled at category level only, or also at field level?
3. Should `vanarrationanddocuments` remain always included, or become config-controlled?
4. Should the first-open category be configurable per form type?
5. Should categories with zero surviving fields but `always_include=true` render an empty
   panel or a placeholder panel?

## Risks

### Risk: Breaking Existing Rendering

Mitigation:

- additive migration
- phased cutover
- migrate low-risk categories first
- keep legacy path available during transition

### Risk: Role Visibility Regression

Mitigation:

- explicit role flags in config
- focused tests for coder/reviewer/site-PI category visibility

### Risk: Mismatch Between Old and New Category Lists

Mitigation:

- do not leave old preprocess and new runtime using different category sources
- cut over preprocess after the runtime service is ready

### Risk: Over-Generalizing Workflow Panels

Mitigation:

- explicitly keep SmartVA and workflow forms out of scope

### Risk: Attachment Rendering Regressions

Mitigation:

- preserve current attachment existence checks
- keep media URL generation in one service
- add focused tests for audio/image/document rows

## Testing Strategy

### Unit / Service Tests

- form-type resolution
- category config loading
- role-based category filtering
- render-mode selection
- field render-type transformation
- PII masking
- category visibility computation

### Integration Tests

- left-nav generation for coder, reviewer, and site PI
- previous/next traversal
- low-risk category render parity against current behavior
- health-history summary behavior
- attachment rendering behavior

### Manual Verification

- verify current WHO 2022 VA coder screen
- verify site-PI interview details visibility
- verify narration/documents media rendering
- verify empty-category behavior
- verify order: category -> subcategory -> field

## Verification Gates Before Removing Legacy Code

Do not remove hardcoded category partials until:

- nav is fully DB-driven
- previous/next uses the same config-driven category list
- standard categories render correctly through the generic path
- `vahealthhistorydetails` parity is confirmed
- `vanarrationanddocuments` parity is confirmed
- role visibility matches current behavior

## Recommended Next Implementation Step

Start with the runtime foundation and category metadata, not the final template rewrite.

Recommended first coding slice:

1. make form-type resolution explicit everywhere
2. add category display config schema
3. seed current WHO 2022 VA category metadata
4. build a service that returns ordered, role-filtered category config for a submission

Only after that should the generic category template be introduced.

## Relationship To Other Plans

- This plan supersedes the "static Social Autopsy partial first" direction as the longer
  target state.
- The Social Autopsy plan can still serve as a short-term bridge if immediate delivery is
  needed before the generic renderer exists.
