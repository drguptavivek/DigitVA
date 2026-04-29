---
title: COD Snapshot Export Implementation Plan
doc_type: plan
status: active
owner: engineering
last_updated: 2026-04-29
---

# COD Snapshot Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a submission-level COD snapshot materialized view and a new data-management CSV export for active coder, reviewer, authoritative, SmartVA, NQA, Social Autopsy, and WHO 2022 bucket reporting.

**Architecture:** Keep the current analytics MVs intact and add one new reporting MV, `va_submission_cod_snapshot_mv`, that centralizes active COD-facing data per submission. The new export endpoint reads from that MV using the existing data-manager scoping and CSV caching path.

**Tech Stack:** Flask, SQLAlchemy, PostgreSQL materialized views, Alembic, pytest, Docker Compose, `uv`

---

### Task 1: Lock the MV contract with failing service tests

**Files:**
- Modify: `tests/services/test_submission_analytics_mv.py`
- Reference: `app/services/submission_analytics_mv.py`

- [ ] Step 1: Add a failing test that creates distinct coder, reviewer, authoritative, SmartVA, NQA, and Social Autopsy rows for one submission and asserts the new MV row keeps them separate.
- [ ] Step 2: Run the targeted failing test inside Docker.
- [ ] Step 3: Add the minimal MV builder and refresh wiring needed for the test.
- [ ] Step 4: Re-run the targeted test until it passes.

### Task 2: Add WHO 2022 bucket mapping coverage to the MV

**Files:**
- Modify: `tests/services/test_submission_analytics_mv.py`
- Modify: `app/services/submission_analytics_mv.py`

- [ ] Step 1: Add a failing test that seeds the WHO 2022 VA COD bucket scheme and asserts bucket mapping for coder, reviewer, authoritative, and SmartVA cause ICDs.
- [ ] Step 2: Run the targeted failing test inside Docker.
- [ ] Step 3: Extend the MV SQL with explicit WHO 2022 mapping joins.
- [ ] Step 4: Re-run the targeted test until it passes.

### Task 3: Add the materialized-view migration and refresh integration

**Files:**
- Create: `migrations/versions/<new_revision>_add_submission_cod_snapshot_mv.py`
- Modify: `app/services/submission_analytics_mv.py`

- [ ] Step 1: Add the Alembic migration that creates the new MV and unique index on `va_sid`.
- [ ] Step 2: Update refresh orchestration so the new MV refreshes with the analytics/reporting set.
- [ ] Step 3: Run migration-oriented tests if available, otherwise run the MV service tests again against the migrated schema.

### Task 4: Add the new CSV export service and route

**Files:**
- Modify: `app/services/data_management_service.py`
- Modify: `app/routes/api/data_management.py`
- Modify: `app/tasks/export_tasks.py`
- Modify: `app/static/js/data_manager_dashboard.js`
- Modify: `tests/routes/test_data_manager_dashboard.py`

- [ ] Step 1: Add a failing route/export test that expects the new endpoint, Excel-safe CSV response, and representative columns from the snapshot MV.
- [ ] Step 2: Run the targeted failing route test inside Docker.
- [ ] Step 3: Add the export service function and route wiring using the existing cached CSV helper path.
- [ ] Step 4: Re-run the targeted route test until it passes.

### Task 5: Document the new reporting baseline

**Files:**
- Create or modify: `docs/policy/data-management-cod-snapshot-export.md`
- Modify: `docs/current-state/submission-analytics.md`
- Modify: `docs/current-state/data-manager-dashboard.md`

- [ ] Step 1: Add or update the policy baseline for the new export semantics.
- [ ] Step 2: Update current-state docs for the new MV and export endpoint.

### Task 6: Verify end-to-end

**Files:**
- Verify only

- [ ] Step 1: Run the focused MV and route tests inside Docker.
- [ ] Step 2: Run any adjacent export or COD bucket tests impacted by the new MV.
- [ ] Step 3: Confirm `git diff` only contains intended implementation and doc updates.
