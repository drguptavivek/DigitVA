---
title: Security Audit — api/dm_kpi/*
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `app/routes/api/dm_kpi/` — Security Audit

## Files Covered

| File | Routes |
|------|--------|
| `dm_kpi_scope.py` | scope configuration endpoints |
| `dm_kpi_grid.py` | grid data |
| `dm_kpi_burndown.py` | burndown chart |
| `dm_kpi_workflow.py` | workflow KPI |
| `dm_kpi_coders.py` | coder KPI |
| `dm_kpi_pipeline.py` | pipeline KPI |
| `dm_kpi_sync.py` | sync KPI |
| `dm_kpi_language.py` | language KPI |

All routes require `@role_required("data_manager")`.

---

## SEC-009 — `dm_kpi_scope.py` returns raw exception string

**Severity:** MEDIUM  
**File:** `api/dm_kpi/dm_kpi_scope.py`  
**Line:** 190

**Description:**  
The scope endpoint returns exception details directly in the JSON response body:

```python
kpi_result = {"status": "error", "reason": str(exc)}
```

The `reason` field containing `str(exc)` may expose SQLAlchemy column names, query
structure, or internal state to the data_manager role.

**Recommendation:**  
Log the exception server-side and return a safe message:

```python
log.error("KPI scope error: %s", exc, exc_info=True)
kpi_result = {"status": "error", "reason": "Could not load scope. See server logs."}
```

---

## No additional findings

- All routes consistently protected by `@role_required("data_manager")`.
- No raw SQL interpolation found across all KPI files.
- Data is scoped to the DM's project/site grants — no cross-DM data leakage found.
- No file-system access in KPI routes.

---

## Positive Controls Verified

- Uniform `@role_required("data_manager")` decoration.
- SQLAlchemy ORM queries with proper parameterisation.
- Responses contain aggregated metrics, not raw PII submissions.
