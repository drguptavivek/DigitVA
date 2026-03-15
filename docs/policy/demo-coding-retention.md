---
title: Demo Coding Retention Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-03-15
---

# Demo Coding Retention Policy

## Purpose

DigitVA supports an admin-only demo coding mode for training, validation, and
product walkthroughs. This document defines how demo-created coding artifacts
must behave so they are visible long enough to inspect, but do not permanently
pollute production workflow state.

## Scope

This policy applies only to coding sessions started through:

- `vademo_start_coding`

It does not change normal coder workflows entered through:

- `vastartcoding`
- `vapickcoding`
- `varesumecoding`
- `varecode`

## Baseline

Current intended baseline:

- demo coding saves the same first-pass artifacts as normal coding:
  - Narrative Quality Assessment
  - Social Autopsy Analysis
  - final COD submission
- demo-created artifacts must remain readable in the UI after save
- a demo-coded submission may appear on the coder dashboard while its demo
  artifacts are still active
- demo-created artifacts are temporary and must expire automatically 6 hours
  after the completed demo coding outcome is recorded

## Retention Window

Current intended baseline:

- the retention window is 6 hours
- the retention timer starts from the persisted demo coding artifact timestamps
- cleanup may run asynchronously; the system does not need to delete records at
  the exact second the 6-hour mark is crossed

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

- while demo artifacts remain active, the coder dashboard may show the
  submission as coded by the demo user
- once the 6-hour retention window expires and cleanup deactivates the demo
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
- whether partial demo work is retained differently from finalized demo work
- whether demo-coded submissions should ever remain excluded from the real
  coding pool after cleanup
- whether demo artifacts require an explicit data-model flag instead of
  inference from workflow/audit state
