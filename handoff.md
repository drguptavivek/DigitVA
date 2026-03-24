---
title: Handoff
doc_type: session-notes
status: active
owner: engineering
last_updated: 2026-03-24
---

# Handoff

## Current State

- Workflow refactor, payload-version linkage, reviewer flow, and SmartVA run-history work complete.
- SmartVA backfill complete for all projects (UNSW01, ICMR01, ZZZ99).
- Data-management UI overhauled (KPI cards, workflow filter, pie chart, section URL sync).
- Legacy workflow states `partial_coding_saved` and `closed` removed.
- All sync/coding/reviewer timeout paths implemented and tested.

## Recent Commits

| Commit | Description |
|--------|-------------|
| `1b27c4a` | Form OK button returns to DM list |
| `325bd3b` | DM triage partial: card layout, footer buttons |
| `1c0ee53` | URL sync on Next/Prev category nav |
| `05cc7d5` | URL sync with active section on DM view |
| `a5e67ec` | Mermaid diagram: 13-state machine |
| `40f8191` | Rate limit: per-user buckets, higher limits |
| `fd8d49d` | DM UI overhaul: KPI cards, workflow filter, pie chart |
| `7cbf702` | Remove legacy workflow states |

## Key Architecture

**Workflow States (13):**
`pending_coding`, `smartva_pending`, `smartva_running`, `coder_allocated`, `coding_in_progress`, `coder_finalized`, `reviewer_eligible`, `reviewer_coding_in_progress`, `reviewer_finalized`, `finalized_upstream_changed`, `not_codeable_by_data_manager`, `not_codeable_by_coder`, `consent_refused`

**Timeout Paths:**
- Coder: `coding_in_progress` → `coder_allocated` (30 min)
- Reviewer: `reviewer_coding_in_progress` → `reviewer_eligible` (30 min)

**SmartVA:**
- Disk-backed: `data/smartva_runs/{project_id}/{form_id}/{form_run_id}/`
- DB: `VaSmartvaFormRun` → `VaSmartvaRun` → `VaSmartvaRunOutput`

## Related Docs

- [`docs/policy/coding-workflow-state-machine.md`](docs/policy/coding-workflow-state-machine.md) — canonical workflow
- [`docs/policy/odk-sync-policy.md`](docs/policy/odk-sync-policy.md)
- [`docs/policy/coding-allocation-timeouts.md`](docs/policy/coding-allocation-timeouts.md)

## Useful Commands

```bash
# Run focused test suites
docker compose exec minerva_app_service uv run pytest tests/services/test_odk_sync_service.py tests/services/test_submission_workflow_service.py tests/services/test_coding_allocation_service.py -q

# SmartVA tests
docker compose exec minerva_app_service uv run pytest tests/services/test_smartva_service.py -q

# Data management tests
docker compose exec minerva_app_service uv run pytest tests/services/test_data_management_service.py -q
```
