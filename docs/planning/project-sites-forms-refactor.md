---
title: Project Sites Forms Refactor Plan
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-03-09
---

# Project, Sites, Forms Refactor Plan

## Purpose

This document captures:

- the current state of the DigitVA data model
- the target state we want to achieve
- the gaps between the two
- a staged refactor plan to move safely from current to target

The immediate goal is to move from a single-project-first schema to a generalized multi-project platform schema, and to separate:

- app-level business entities such as `Project`, `Site`, and `FormType`
- external ODK source identifiers such as `odk_project_id` and `odk_form_id`
- operational deployment mappings that connect an app project/site context to an ODK form


## Current State

### Current implementation posture

The current schema and code should be understood as a single-project-first implementation.

It is not a generalized multi-project domain model that happens to have some restrictive constraints. Instead, it is a schema that was shaped around one active project deployment and later accumulated more logic on top of that assumption.

This matters because the refactor is not just a cleanup of relationships. It is a shift from:

- one-project-first modeling

to:

- multi-project, multi-site, multi-ODK-source platform modeling

### Current conceptual model in code

The current implementation effectively models:

- one primary `Project` has many `Site`s
- one `Site` belongs to exactly one `Project`
- one `Form` belongs to one `Project` and one `Site`
- one `Submission` belongs to one `Form`

In practice, the seeded and operational code paths are centered on one project deployment.

### Current tables

#### `va_research_projects`

Represents a project master record.

In the current system, this behaves more like the top-level identifier for the single onboarded project context than as part of a truly generalized project platform.

Key fields:

- `project_id`
- `project_code`
- `project_name`
- `project_nickname`

#### `va_sites`

Represents a site, but currently as project-scoped rather than globally reusable.

Key fields:

- `site_id`
- `project_id`
- `site_name`
- `site_abbr`

Problem:

- `site_id` is modeled as belonging to exactly one project because `va_sites` has a direct `project_id` foreign key
- this design makes sense only in a single-project-first implementation or where sites are treated as project-local

#### `va_forms`

Represents an app form record that also carries ODK identifiers.

Key fields:

- `form_id`
- `project_id`
- `site_id`
- `odk_form_id`
- `odk_project_id`
- `form_type`

Problems:

- this table mixes app identity, site/project assignment, standardized form meaning, and ODK source identity
- `form_id` is being used as an operational primary key and also as an encoded naming convention
- `form_type` is a plain string, not a reusable master entity
- the table structure reflects one-project-first onboarding rather than a reusable deployment model

#### `va_submissions`

Represents imported VA submissions.

Key fields:

- `va_sid`
- `va_form_id`
- raw and derived submission payload fields

Operational meaning:

- each submission points to `va_forms.form_id`
- downstream rendering, permissions, sync, SmartVA preprocessing, and media access all depend on this linkage

### Current identifier behavior

The code currently assumes a synthetic internal form identifier such as:

- `UNSW01NC0101`

This effectively encodes:

- `project_id = UNSW01`
- `site_id = NC01`
- sequence or variant = `01`

This is convenient for a single narrow deployment, but it hardcodes business structure into an identifier and makes reuse difficult.

It is a reasonable shortcut for a single-project system, but it becomes a liability once projects, reusable sites, reusable form types, and multiple ODK sources are introduced.

### Current ODK behavior

ODK source identifiers are stored directly on `va_forms`:

- `odk_project_id`
- `odk_form_id`

The sync process uses those values to download and process data. This means the current `va_forms` table is acting as both:

- an app-side master/config record
- an external-source connection mapping

This is acceptable in a one-project-first design, but it is not the right abstraction once onboarding must support multiple projects and possibly multiple ODK servers.


## Target State

### Target conceptual model

The target business model should be:

- `Site` is a standalone master entity
- `FormType` is a standalone master entity
- `Project` is a standalone master entity
- a `Project` can involve multiple `Site`s
- a `Site` can participate in multiple `Project`s
- a project can ingest data from one or more ODK forms
- each onboarded ODK form must be associated with:
  - one app project
  - one site within that project
  - one standardized form type
  - one ODK server connection
  - one ODK project/form pair

### Core modeling principle

We need to separate three different concerns:

1. Business identity in this app
2. External source identity in ODK
3. Deployment mapping between the two

### Target entities

#### `projects`

App-side business project.

Suggested fields:

- `project_id`
- `project_code`
- `project_name`
- `project_nickname`
- `status`
- audit timestamps

#### `sites`

Standalone site master.

Suggested fields:

- `site_id`
- `site_name`
- `site_abbr`
- optional geographic or organization metadata
- `status`
- audit timestamps

#### `form_types`

Standardized questionnaire/rendering type used by the app.

Suggested fields:

- `form_type_id`
- `form_type_name`
- optional version
- optional render template family
- optional mapping family
- optional SmartVA default settings
- `status`

Examples:

- `who_va_2022`
- future variants if needed

#### `project_sites`

Join table between projects and sites.

Suggested fields:

- `project_site_id` or composite key `(project_id, site_id)`
- `project_id`
- `site_id`
- `status`
- audit timestamps

Purpose:

- expresses that a project includes a site
- supports many-to-many between projects and sites

#### `odk_server_connections`

Reusable ODK server connection definition.

Suggested fields:

- `connection_id`
- `connection_name`
- `base_url`
- `username`
- `password_encrypted` or secret reference
- optional authentication metadata
- `status`
- audit timestamps

Security note:

- do not return stored passwords in clear text after save
- store encrypted secrets or secret references
- restrict access to users who can manage integrations

#### `project_form_deployments`

This is the most important new operational table.

It defines how data enters the app.

Suggested fields:

- `deployment_id`
- `project_id`
- `site_id`
- `project_site_id` if we want stronger normalization
- `form_type_id`
- `connection_id`
- `odk_project_id`
- `odk_form_id`
- optional display mapping override key
- optional active date range
- `status`
- audit timestamps

Purpose:

- binds one project/site context to one standardized form type and one external ODK form
- becomes the bridge between business context and ingestion source

#### `va_submissions`

Submissions should point to deployment, not to a synthetic encoded form id.

Target linkage:

- `va_submissions.deployment_id` -> `project_form_deployments.deployment_id`

This allows us to derive:

- which project the submission belongs to
- which site it belongs to
- which form type drives display and mapping
- which ODK connection and ODK source produced it


## Current-to-Target Mapping

### Current `va_research_projects`

Keep conceptually, rename only if desired.

Current role:

- valid as the project master

Target role:

- `projects`

### Current `va_sites`

Needs redesign.

Current role:

- site master mixed with project membership

Target role:

- standalone `sites` master

Required change:

- remove direct `project_id` ownership from site master
- move project membership into `project_sites`

### Current `va_forms`

Should be split conceptually.

Current role:

- internal form identity
- project/site assignment
- ODK source mapping
- form type indicator
- SmartVA defaults

Target role:

- split across:
  - `form_types`
  - `project_form_deployments`
  - possibly a separate form type settings table if needed

### Current `va_submissions.va_form_id`

Needs redesign.

Current role:

- foreign key to `va_forms.form_id`

Target role:

- foreign key to `project_form_deployments.deployment_id`


## Why This Refactor Is Needed

### Business correctness

The current schema reflects a single-project-first implementation and does not support the actual target business rules:

- a site can belong to more than one project
- ODK project/form identifiers are external source identifiers, not app business identifiers
- standardized form types should be reusable across many project/site deployments

### Operational clarity

The current model overloads `form_id` with too many meanings. This creates confusion in:

- permissions
- sync logic
- dashboard reporting
- display mapping
- media resolution

### Extensibility

The target model supports:

- multiple projects reusing the same site
- multiple projects and deployments reusing the same standardized form type
- multiple ODK servers
- future onboarding UI for mapping external forms into app concepts

The current model does not fail because it is poorly designed for its original purpose. It fails because the platform scope has expanded beyond that original one-project assumption.


## Refactor Scope

### In scope

- schema redesign for project/site/form relationships
- support for reusable sites
- support for reusable form types
- support for ODK server connection records
- support for project-specific ODK deployments
- submission linkage changes
- refactor of sync and permission code to use deployment identity

### Out of scope for first pass

- complete UI redesign
- changing the fundamental coding/review workflow
- SmartVA algorithm changes
- major styling or template overhauls unrelated to the data model


## Proposed Target Schema

### Option A: Minimal and practical

Use these tables:

- `projects`
- `sites`
- `form_types`
- `project_sites`
- `odk_server_connections`
- `project_form_deployments`
- `va_submissions`

Recommended key relationships:

- `project_sites.project_id` -> `projects.project_id`
- `project_sites.site_id` -> `sites.site_id`
- `project_form_deployments.project_id` -> `projects.project_id`
- `project_form_deployments.site_id` -> `sites.site_id`
- `project_form_deployments.form_type_id` -> `form_types.form_type_id`
- `project_form_deployments.connection_id` -> `odk_server_connections.connection_id`
- `va_submissions.deployment_id` -> `project_form_deployments.deployment_id`

Constraint recommendation:

- enforce that `(project_id, site_id)` used by a deployment exists in `project_sites`

### Option B: More normalized

Same as above, but `project_form_deployments` references `project_site_id` instead of separate `project_id` and `site_id`.

This is more normalized, but Option A is easier to adopt incrementally in the current codebase.

Recommendation:

- start with Option A unless stronger relational strictness is needed immediately


## Application Architecture Impact

### Sync pipeline

Current behavior:

- sync iterates active `va_forms`
- uses `odk_project_id` and `odk_form_id`
- stamps imported submissions with `form_def = va_form.form_id`

Target behavior:

- sync iterates active `project_form_deployments`
- uses deployment-level `connection_id`, `odk_project_id`, and `odk_form_id`
- stamps imported submissions with `deployment_id`
- derives project/site/form type through the deployment

### Rendering and mapping

Current behavior:

- rendering utilities commonly receive `va_form_id`
- form-specific logic is implicitly tied to current form identity

Target behavior:

- rendering should resolve `form_type` from submission deployment
- display and mapping should be driven by `form_type`
- deployment-level overrides can be added if needed later

### Permissions

Current behavior:

- user permissions are form-based, with `permission` JSON containing values that appear to be form IDs or site IDs depending on workflow

Target behavior:

- permission model must become explicit
- decide whether access is granted by:
  - project
  - project-site
  - deployment
  - form type within project/site

Recommended direction:

- keep access scoped by project-site or deployment, not by synthetic encoded form ID

### Reporting

Current behavior:

- some reporting logic conflates `site_id` and `va_form_id`

Target behavior:

- reporting should aggregate through deployment to project and site
- no assumptions should be made that a site ID equals a form ID suffix


## Migration Strategy

### Phase 0: Define target language and invariants

Before any code changes:

- agree on canonical terminology:
  - project
  - site
  - form type
  - ODK server connection
  - project form deployment
- agree on access control scope
- agree on whether a project may use multiple ODK server connections

### Phase 1: Introduce new schema alongside old schema

Add new tables without deleting existing ones:

- `form_types`
- `project_sites`
- `odk_server_connections`
- `project_form_deployments`

Keep current tables operational while backfilling.

Benefits:

- lower-risk rollout
- easier data validation
- allows old and new logic to coexist temporarily

### Phase 2: Seed and backfill master data

Backfill from current records:

- create standalone `sites` from current `va_sites`
- create `project_sites` from current site/project pairs
- create initial `form_types` from current `va_forms.form_type`
- create initial `project_form_deployments` from current `va_forms`

Important:

- each old `va_forms` row should map to one deployment
- preserve old `form_id` as a legacy reference field if needed during transition

### Phase 3: Add deployment linkage to submissions

Add `deployment_id` to `va_submissions`.

Backfill:

- map each current `va_form_id` to the corresponding newly created deployment

Transition rule:

- for a temporary period, keep both `va_form_id` and `deployment_id`

### Phase 4: Refactor sync to use deployments

Update sync code so it:

- loads active deployments
- resolves the correct ODK connection
- downloads from deployment-level `odk_project_id` and `odk_form_id`
- writes submissions using `deployment_id`

This is the first major behavioral shift.

### Phase 5: Refactor app logic to resolve business context through deployment

Update code paths that currently rely on `va_form_id`:

- dashboard queries
- permission validation
- media serving
- rendering helpers
- SmartVA preprocessing and output storage

Each path should derive:

- project
- site
- form type

from the submission deployment record.

### Phase 6: Redesign onboarding flows

Add admin workflows for:

- create project
- create site
- associate project with sites
- create or select ODK server connection
- register deployment:
  - choose project
  - choose site
  - choose form type
  - assign ODK project/form

### Phase 7: Retire old schema and assumptions

After full validation:

- stop writing legacy `va_form_id` references
- deprecate or remove old `va_forms` semantics
- remove code that assumes encoded form IDs
- clean up legacy seed logic


## Data Migration Notes

### Backfill example from current records

Current:

- project `UNSW01`
- site `NC01`
- form `UNSW01NC0101`
- ODK project `3`
- ODK form `NC01_DS_WHOVA2022`
- form type `WHO VA 2022`

Target:

- `projects`: `UNSW01`
- `sites`: `NC01`
- `project_sites`: (`UNSW01`, `NC01`)
- `form_types`: `WHO VA 2022`
- `project_form_deployments`:
  - `project_id = UNSW01`
  - `site_id = NC01`
  - `form_type_id = who_va_2022`
  - `odk_project_id = 3`
  - `odk_form_id = NC01_DS_WHOVA2022`
  - `legacy_form_id = UNSW01NC0101` if useful during migration

### Backward compatibility strategy

During transition:

- preserve legacy identifiers in migration tables or compatibility columns
- avoid breaking references in one release
- add compatibility lookup helpers if necessary


## Security Considerations

### ODK credentials

Do not store plaintext passwords casually.

Minimum expectations:

- encrypt stored credentials
- avoid exposing current password values in UI responses
- redact credentials in logs
- scope editing/viewing to admin roles

### Multi-server support

Connection records should be explicit and auditable.

Recommended fields:

- who created/updated the connection
- last successful sync timestamp
- last failed sync timestamp
- connection status


## Key Risks

### Risk 1: Permission model ambiguity

The current permission JSON appears to mix access concepts. A refactor without first clarifying permission scope will create regressions.

Mitigation:

- define the future permission unit before code changes begin

### Risk 2: Reporting assumptions based on encoded IDs

Some current queries appear to infer site context from submission or form identifiers.

Mitigation:

- audit all queries that use `va_form_id`, `site_id`, or `va_sid` suffix parsing

### Risk 3: Mapping logic tied implicitly to current form identity

Rendering and preprocessing may contain hidden assumptions that a particular form ID corresponds to a specific questionnaire structure.

Mitigation:

- move mapping resolution to `form_type`
- identify any deployment-specific exceptions explicitly

### Risk 4: Credential handling

Adding ODK server connections increases security risk.

Mitigation:

- design secrets storage before implementing connection management UI


## Recommended Implementation Order

1. Finalize target schema and naming.
2. Define future permission scope.
3. Add new tables and migrations.
4. Backfill current data into new structures.
5. Add `deployment_id` to submissions.
6. Refactor sync to read from deployments and connections.
7. Refactor rendering and permission resolution to use deployment and form type.
8. Add admin onboarding flows for project/site/connection/deployment management.
9. Remove legacy assumptions and obsolete columns after validation.


## Open Questions

These need explicit answers before implementation starts:

- Can one project use more than one ODK server connection?
- Can one project-site pair have more than one deployment for the same form type?
- Should form type versioning be modeled now or later?
- Should permissions be scoped to project, project-site, or deployment?
- Do we need deployment-specific mapping overrides, or is form-type-only mapping enough?
- Should old `form_id` values be preserved permanently as business-visible legacy identifiers, or only as migration artifacts?


## Immediate Next Step

Before code changes, create a technical design follow-up that defines:

- exact new table names and columns
- migration/backfill steps
- permission model changes
- sync refactor details
- compatibility strategy for existing data and workflows
