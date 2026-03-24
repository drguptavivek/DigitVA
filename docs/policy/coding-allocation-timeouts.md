---
title: Coding Allocation Timeout Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-24
---

# Coding Allocation Timeout Policy

## Baseline

DigitVA treats coder and reviewer allocations as time-bound workflow
reservations.

Current baseline:

- active coding and reviewing allocations older than `1 hour` are considered
  stale
- stale allocations must be released automatically
- stale allocation release must distinguish first-pass coding, recode episodes,
  and reviewer sessions

## Required behavior — first-pass coder

When a first-pass coding allocation becomes stale:

- deactivate the active `va_allocations` row for coding
- deactivate unfinished active `va_initial_assessments` rows for the timed-out
  coder
- deactivate first-pass `va_narrative_assessments` rows for the timed-out coder
- deactivate first-pass `va_social_autopsy_analyses` rows for the timed-out
  coder
- return canonical workflow state to `ready_for_coding`
- write an audit log entry for the release

## Required behavior — recode

When a recode coding allocation becomes stale:

- deactivate the active `va_allocations` row for coding
- deactivate unfinished active `va_initial_assessments` rows for the timed-out
  coder
- abandon the active recode episode
- preserve the currently authoritative final COD
- preserve saved NQA and Social Autopsy analysis artifacts from the recode
  window
- return canonical workflow state to `coder_finalized`
- write an audit log entry for the release

## Required behavior — reviewer session

When a reviewer allocation becomes stale:

- deactivate the active `va_allocations` row for reviewing
- deactivate active `va_reviewer_reviews` rows for the timed-out reviewer
- deactivate active `va_narrative_assessments` rows for the timed-out reviewer
- deactivate active `va_social_autopsy_analyses` rows for the timed-out
  reviewer
- return canonical workflow state to `reviewer_eligible`
- write an audit log entry for the release

Rationale: the reviewer final COD submission is the only terminal action for a
reviewer session. All intermediate saves (NQA, Social Autopsy, reviewer NQA)
are partial saves. If the session times out before the final COD is submitted,
all intermediate artifacts disappear and the submission returns to
`reviewer_eligible` so a fresh reviewer session can start.

## Invariant for all timeout paths

The release action must not:

- delete assessment or review records
- alter submission content
- replace the authoritative final COD with unfinished draft work

## Execution model

The timeout release must run in two ways:

- hourly as a scheduled background task (`release_stale_coding_allocations_task`
  covers both coder and reviewer allocations)
- opportunistically:
  - when a coder starts normal coding (`start_coding` in `coding_service.py`)
  - when a reviewer starts a reviewer session (`start_reviewer_coding` in
    `reviewer_coding_service.py`)

This provides both proactive cleanup and local recovery even if the scheduled
task has not run yet.
