---
title: Coding Allocation Timeout Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-14
---

# Coding Allocation Timeout Policy

## Baseline

DigitVA treats coder allocations as time-bound workflow reservations.

Current baseline:

- active coding allocations older than `1 hour` are considered stale
- stale coding allocations must be released automatically
- stale allocation release must distinguish first-pass coding from recode
  episodes

## Required behavior

When a coding allocation becomes stale:

- deactivate the active `va_allocations` row for coding
- write an audit log entry for the release

First-pass coding timeout reversion:

- deactivate unfinished active `va_initial_assessments` rows for the timed-out
  coder
- deactivate first-pass `va_narrative_assessments` rows for the timed-out coder
- deactivate first-pass `va_social_autopsy_analyses` rows for the timed-out
  coder
- return canonical workflow state to `ready_for_coding`

Recode timeout reversion:

- deactivate unfinished active `va_initial_assessments` rows for the timed-out
  coder
- abandon the active recode episode
- preserve the currently authoritative final COD
- preserve saved NQA and Social Autopsy analysis artifacts from the recode
  window
- return canonical workflow state to `coder_finalized`

The release action must not:

- delete assessment or review records
- alter submission content
- replace the authoritative final COD with unfinished draft work

## Execution model

The timeout release must run in two ways:

- hourly as a scheduled background task
- opportunistically when a coder starts normal coding

This provides both proactive cleanup and local recovery even if the scheduled
task has not run yet.
