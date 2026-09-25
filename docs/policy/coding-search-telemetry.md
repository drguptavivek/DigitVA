---
title: Coding Search Telemetry (Phase 0)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-25
---

# Coding search telemetry (`digitva-zpe.3`, phase 0 of the search plan)

Evidence before build: record what clinicians actually type into the COD
coding search, so the vocabulary (`docs/policy/icd-coding-search-vocabulary.md`)
grows from real usage and the Phase-B semantic decision is made on data.

## What is captured

One row per coding-search request, plus (when the client provides it) the
code eventually chosen:

- `search_id` — client-generated UUID (one per query; the browser remembers
  the last one used for the COD field and sends it back on save)
- `surface` — `icd10_coding` | `icd11_coding`
- `query_text` — the typed query, whitespace-collapsed, hard-truncated at 128
  characters
- `result_count`, `zero_results`, `vocabulary_hit` (any vocabulary row in the
  results), `latency_ms`
- `role` — coder / coding_tester / reviewer / admin. **No user id, no va_sid,
  no IP** — the query term and role are the analytical payload.
- `chosen_code`, `chosen_rank` (rank in that search's result list), filled on
  the COD save when the client forwards the last `search_id`; nullable.

## Behavioural rules

- Telemetry MUST never break or slow the search path: the insert happens
  after the response payload is built, wrapped so any failure is logged and
  swallowed. No search is refused, deferred or altered because of telemetry.
- The endpoints' authorization and rate limits are unchanged.
- Retention 90 days: a scheduled cleanup deletes older rows; the table is
  operational data, exported as CSV (`/admin/api/coding-search-telemetry/
  export.csv`, admin role) for analysis. No panel UI in phase 0 beyond the
  export route.
- Table name `cod_search_telemetry`, deliberately outside the `mas_*` /
  `map_*` / `auth_*` conventions (operational log, not master data or
  authorization; owner informed 2026-09-25).
- Terms proposed from telemetry enter `mas_icd_search_terms` only through an
  admin action (`source='telemetry'`); nothing auto-seeds.
