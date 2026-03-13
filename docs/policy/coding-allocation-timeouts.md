---
title: Coding Allocation Timeout Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-03-13
---

# Coding Allocation Timeout Policy

## Baseline

DigitVA treats coder allocations as time-bound workflow reservations.

Current baseline:

- active coding allocations older than `1 hour` are considered stale
- stale coding allocations must be released automatically
- stale allocation release must not discard saved Step 1 COD work

## Required behavior

When a coding allocation becomes stale:

- deactivate the active `va_allocations` row for coding
- preserve any active `va_initial_assessments` row for the same submission
- write an audit log entry for the release

The release action must not:

- deactivate the initial assessment
- delete assessment or review records
- alter submission content

## Execution model

The timeout release must run in two ways:

- hourly as a scheduled background task
- opportunistically when a coder starts normal coding

This provides both proactive cleanup and local recovery even if the scheduled
task has not run yet.
