---
title: Coding Debug Stats API Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-07
---

# Coding Debug Stats API Policy

## Purpose

Provide an operator-safe runtime diagnostic endpoint to explain exactly why a
coder can or cannot see cases in the coding dashboard.

## Endpoint

- `GET /api/v1/coding/debug-stats`

## Access

Allowed roles:

- `coder`
- `admin`

The response must be scoped to the authenticated caller's current grants and
language settings only.

## Response Baseline

The endpoint must include:

- caller identity (`user_id`, `email`, `is_admin`)
- coder scope (`form_ids`, random vs pick split, normalized languages)
- per-form mapping status (`project_id`, `site_id`, `project_site_status`)
- workflow visibility breakdown:
  - state counts within coder form scope
  - coder-ready state list
  - ready-for-coding counts after language filtering (by language, by form, total)

## Security And Data Handling

- read-only diagnostics only
- no mutation of workflow, grants, or allocations
- no credentials or secret values in output
- avoid raw payload/PII fields; use aggregate counts and identifiers only
