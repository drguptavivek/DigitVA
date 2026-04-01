---
title: Data Manager Workflow Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-04-01
---

# Data Manager Workflow Policy

## Purpose

The `data_manager` role exists for data-quality triage and operational review of
submissions before or outside coder workflow.

It is not a coding role and it is not a reviewer role.

## Scope Rules

`data_manager` grants may be issued at either:

- `project`
- `project_site`

A project-scoped data manager may act across all sites in the granted project.

A project-site-scoped data manager may act only on submissions that belong to
that project-site pair.

## Core Capabilities

A data manager may:

- browse all submissions in scope
- open an individual submission in read-only mode
- trigger a scoped form sync from the data-manager dashboard
- trigger a single-submission refresh from ODK for a submission in scope
- mark a submission as Not Codeable from the data-management workflow
- document the reason and optional notes for that decision

A data manager may not:

- start coding
- resume coder allocations
- submit initial COD
- submit final COD
- submit reviewer QA
- override coder or reviewer workflow outcomes

## Data Manager Not Codeable Outcome

When a data manager marks a submission as Not Codeable:

- the decision must be stored as a data-manager-specific workflow record
- the actor must be the data manager, not a coder
- the reason and optional details must be auditable

This outcome is distinct from coder Not Codeable.

DigitVA must not reuse coder-owned workflow records in a way that makes it look
like a coder made the data-manager decision.

## Effect On Coder Allocation

Any submission with an active data-manager Not Codeable outcome must be excluded
from new coder allocation.

This exclusion applies to:

- normal coder assignment
- random/demo coder assignment

The purpose is to stop known bad submissions from entering coder workflow while
the issue is unresolved.

## Visibility Model

The data manager dashboard should be scope-based, not allocation-based.

That means:

- visible submissions are determined by project or project-site grant scope
- visibility is not limited to cases already worked on by the same user

The dashboard should expose local operational state so the data manager does
not need to use ODK Central directly.

At minimum the dashboard must show:

- canonical local workflow state
- ODK review state mirrored locally from ODK Central
- local sync issue status for the submission

The dashboard may also expose filtered CSV exports for operational review, but
those exports must protect PII.

Export policy:

- export scope must respect the same project / project-site grants as the
  dashboard table
- export content must respect the current dashboard filters
- exports must omit payload fields marked as PII in field mapping
- exports must omit direct local identifiers that should not appear in bulk
  operational extracts
- exports may retain non-PII narrative text needed for operational review
- SmartVA-specific exports must not include the full raw VA payload when a
  narrower SmartVA-specific shape is sufficient

For pending `finalized_upstream_changed` submissions, data managers may also:

- open a shared `View Changes` modal from the dashboard
- open the same `View Changes` modal from the read-only submission detail page
- review:
  - `Data Changes`
  - `Metadata Changes`
  - `Formatting-Only Changes`
- choose `Accept And Recode`, which clears old assigned ICD codes and returns
  the form for recoding
- choose `Keep Current ICD Decision`, which adopts the new upstream ODK data
  locally while preserving the current finalized ICD Code decision and
  finalized workflow state

Policy boundary:

- upstream review actions from these modals are local DigitVA workflow
  resolution action
- modal upstream review actions do not write an ODK rejection comment
- this is distinct from data-manager Not Codeable triage in `vadmtriage`,
  which still writes ODK `hasIssues` review state and comment text back to ODK
  Central

## ODK Sync Visibility

The data-manager dashboard is also the operator-facing view for submission-level
ODK sync health within the data manager's scope.

Policy:

- sync must import all submissions from the mapped ODK form, including rows
  where consent is `no` or missing
- ODK review state must be stored locally and shown on the data-manager
  dashboard
- if a locally tracked submission is no longer present in active ODK
  submissions, DigitVA must record a local sync issue and surface it on the
  dashboard
- a data manager may trigger:
  - a full sync for one scoped form
  - a targeted refresh for one scoped submission
- a targeted refresh must update:
  - the local submission payload
  - attachments for that submission
  - SmartVA result for that submission
  - local sync-issue status for the parent form

## Audit Expectations

The audit trail should make these actions visible:

- data manager opened a submission
- data manager marked a submission Not Codeable
- data manager updated or cleared that outcome if future workflow allows it

The audit language should clearly distinguish data-manager decisions from coder
decisions.
