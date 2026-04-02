---
title: Demo Coding Retention Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-04-02
---

# Demo Coding Retention Policy

## Purpose

DigitVA supports two demo/training patterns:

- admin-started demo sessions on ordinary projects
- project-declared demo/training projects

This document defines how demo-created coding artifacts must behave so they are
visible long enough to inspect, but do not permanently pollute production
workflow state.

## Scope

This policy applies to coding sessions started through:

- `vademo_start_coding`

That action may now come from either:

- an admin-started demo session on a normal project
- a submission belonging to a project with
  `va_project_master.demo_training_enabled = true`

It does not change normal non-demo coder workflows entered through:

- `vastartcoding`
- `vapickcoding`
- `varesumecoding`
- `varecode`

## Baseline

Current intended baseline:

- demo/training coding saves the same first-pass artifacts as normal coding:
  - Narrative Quality Assessment
  - Social Autopsy Analysis
  - final COD submission
- demo-created artifacts must remain readable in the UI after save
- a demo-coded submission may appear on the coder dashboard while its demo
  artifacts are still active
- project-declared demo/training projects are open training pools:
  - no project-specific coder grant is required
  - any active authenticated user may enter the coder flow for those project
    forms
  - non-demo projects still require normal coder grants
- demo-created artifacts are temporary and must expire automatically:
  - after 6 hours for admin-started demo sessions on normal projects
  - after `va_project_master.demo_retention_minutes` for project-declared
    demo/training projects

## Retention Window

Current intended baseline:

- active demo/training coding allocations are revoked after 15 minutes if not
  completed
- the retention window is 6 hours for admin-started demo sessions on ordinary
  projects
- the retention window is project-configurable in minutes for
  `demo_training_enabled` projects, with a default of 10 minutes
- the retention timer starts from the persisted demo coding artifact timestamps
- cleanup may run asynchronously; the system does not need to delete records at
  the exact second the 6-hour mark is crossed

## Dashboard Entry

Current intended baseline:

- the normal coder dashboard should surface a dedicated `DEMO-CODING` shortcut
  whenever the current user can see at least one `demo_training_enabled`
  project
- that shortcut should preselect the first available demo/training project on
  the page instead of sending the user to the admin-only testing flow
- the dashboard should show a plain-language warning on the page:
  - these are demo-training forms
  - completed codes persist for 10 minutes by default unless the project sets a
    different `demo_retention_minutes` value
  - incomplete demo/training allocations are revoked after 15 minutes
- the existing `Admin Testing Coding` action remains admin-only and is still
  reserved for ad hoc demo sessions on ordinary non-demo projects

## Cleanup Outcome

When the retention window expires for a demo-coded submission, the system must:

- deactivate the demo-created final COD record
- deactivate the demo-created Narrative Quality Assessment row
- deactivate the demo-created Social Autopsy Analysis row
- clear any authoritative-final pointer that references the expired demo final
  COD
- restore the submission to the normal non-demo workflow state implied by the
  remaining active records

If no non-demo terminal record remains, the submission should return to
`ready_for_coding`.

## Dashboard Behavior

Current intended baseline:

- while a demo/training allocation is still active, the user may see
  `Continue Pending VA Coding`
- for demo/training projects that continue button lasts only until the 15-minute
  allocation timeout is reached
- while demo artifacts remain active, the coder dashboard may show the
  submission as coded by the demo user
- once the relevant retention window expires and cleanup deactivates the demo
  artifacts, the submission must no longer appear as completed in coder history
  for that demo user

## Auditability

Current intended baseline:

- demo allocation creation must remain auditable
- demo cleanup must write submission audit entries for each artifact it
  deactivates
- the cleanup audit trail must make it clear that the removal happened because
  of demo-retention expiry, not because of ordinary coding timeout

## Change Control

Any future change must explicitly document:

- whether the demo retention window remains 6 hours
- whether the 15-minute demo allocation lock remains fixed or becomes
  configurable
- whether partial demo work is retained differently from finalized demo work
- whether demo-coded submissions should ever remain excluded from the real
  coding pool after cleanup
- whether demo artifacts require an explicit data-model flag instead of
  inference from workflow/audit state
