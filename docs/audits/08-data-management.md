---
title: "Route Audit — data_management Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# data_management Blueprint Audit

**Files:**
- Page routes: `app/routes/data_management.py` (`/data-management/`)
- API routes: `app/routes/api/data_management.py` (`/api/v1/data-management/`)
- Analytics API: `app/routes/api/analytics.py` (`/api/v1/analytics/`)

## Page Routes (`/data-management/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/data-management/` | `@role_required("data_manager")` | `@role_required` | data_manager | `get_data_manager_projects()` + `get_data_manager_project_sites()` | No |
| 2 | GET | `/data-management/view/<va_sid>` | `@role_required("data_manager")` | `@role_required` | data_manager | `has_data_manager_submission_access()` | No (audit read) |
| 3 | GET | `/data-management/submissions/<va_sid>/odk-edit` | `@role_required("data_manager")` | `@role_required` | data_manager | `dm_odk_edit_url()` | Yes (redirect) |

## API Routes (`/api/v1/data-management/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 4 | GET | `/api/v1/data-management/submissions` | `@role_required("data_manager")` | `@role_required` | data_manager | `dm_submissions_page()` | No |
| 5 | GET | `/api/v1/data-management/submissions/export.csv` | `@role_required("data_manager")`, `@limiter` | `@role_required` | data_manager | Scoped | No |
| 6 | GET | `/api/v1/data-management/submissions/export-smartva-input.csv` | `@role_required("data_manager")`, `@limiter` | `@role_required` | data_manager | Scoped | No |
| 7 | GET | `/api/v1/data-management/submissions/export-smartva-results.csv` | `@role_required("data_manager")`, `@limiter` | `@role_required` | data_manager | Scoped | No |
| 8 | GET | `/api/v1/data-management/submissions/export-smartva-likelihoods.csv` | `@role_required("data_manager")`, `@limiter` | `@role_required` | data_manager | Scoped | No |
| 9 | GET | `/api/v1/data-management/kpi` | `@role_required("data_manager")`, `@limiter` | `@role_required` | data_manager | `get_data_manager_projects()` / `get_data_manager_project_sites()` | No |
| 10 | GET | `/api/v1/data-management/filter-options` | `@role_required("data_manager")`, `@limiter` | `@role_required` | data_manager | `dm_filter_options()` | No |
| 11 | GET | `/api/v1/data-management/submissions/<va_sid>/upstream-change-details` | `@role_required("data_manager","admin")`, `@limiter` | `@role_required` | data_manager, admin | `dm_upstream_change_details()` | No |
| 12 | POST | `/api/v1/data-management/forms/<form_id>/sync` | `@role_required("data_manager")` | `@role_required` | data_manager | `dm_form_in_scope()` | Yes |
| 13 | POST | `/api/v1/data-management/sync/preview` | `@role_required("data_manager")` | `@role_required` | data_manager | `dm_scoped_forms()` | No |
| 14 | GET | `/api/v1/data-management/sync/runs` | `@role_required("data_manager")` | `@role_required` | data_manager | Scoped forms | No |
| 15 | GET | `/api/v1/data-management/project-site-submissions` | `@role_required("data_manager")`, `@limiter` | `@role_required` | data_manager | Scoped | No |
| 16 | POST | `/api/v1/data-management/submissions/<va_sid>/sync` | `@role_required("data_manager")` | `@role_required` | data_manager | `has_data_manager_submission_access()` | Yes |
| 17 | POST | `/api/v1/data-management/submissions/<va_sid>/accept-upstream-change` | `@role_required("data_manager","admin")` | `@role_required` | data_manager, admin | `dm_accept_upstream_change()` | Yes |
| 18 | POST | `/api/v1/data-management/submissions/<va_sid>/reject-upstream-change` | `@role_required("data_manager","admin")` | `@role_required` | data_manager, admin | `dm_reject_upstream_change()` | Yes |
| 19 | POST | `/api/v1/data-management/submissions/<va_sid>/screening-pass` | `@role_required("data_manager","admin")` | `@role_required` | data_manager, admin | `dm_screening_pass()` | Yes |
| 20 | POST | `/api/v1/data-management/submissions/<va_sid>/screening-reject` | `@role_required("data_manager","admin")` | `@role_required` | data_manager, admin | `dm_screening_reject()` | Yes |

## Analytics API (`/api/v1/analytics/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 21 | GET | `/api/v1/analytics/kpi` | `@role_required("data_manager")` | `@role_required` | data_manager | `_dm_scope_filter()` | No |
| 22 | GET | `/api/v1/analytics/submissions/by-date` | `@role_required("data_manager")` | `@role_required` | data_manager | `_dm_scope_filter()` | No |
| 23 | GET | `/api/v1/analytics/submissions/by-week` | `@role_required("data_manager")` | `@role_required` | data_manager | `_dm_scope_filter()` | No |
| 24 | GET | `/api/v1/analytics/submissions/by-month` | `@role_required("data_manager")` | `@role_required` | data_manager | `_dm_scope_filter()` | No |
| 25 | GET | `/api/v1/analytics/demographics` | `@role_required("data_manager")`, `@limiter.limit("120/min")` | `@role_required` | data_manager | `build_dm_mv_filter_conditions()` | No |
| 26 | GET | `/api/v1/analytics/workflow` | `@role_required("data_manager")` | `@role_required` | data_manager | `_dm_scope_filter()` | No |
| 27 | GET | `/api/v1/analytics/cod` | `@role_required("data_manager")` | `@role_required` | data_manager | `_dm_scope_filter()` | No |
| 28 | POST | `/api/v1/analytics/mv/refresh` | `@role_required("data_manager")`, `@limiter.limit("1/min")` | `@role_required` | data_manager | N/A (global op, DM-only) | Yes |

## Scoping Details

### Data Manager Scoping
- **Grant resolution:**
  - `get_data_manager_projects()` — project-level grants
  - `get_data_manager_project_sites()` — project-site-level grants as `(project_id, site_id)` tuples
- **Scope enforcement:**
  - Dashboard queries filter by both project and project-site grants
  - Per-submission routes check `has_data_manager_submission_access(project_id, site_id)`
  - MV-based analytics use `_dm_scope_filter()` with expanded `(project_id, site_id)` pairs
- **Form-level scoping:** `dm_form_in_scope()` and `dm_scoped_forms()` for sync/preview operations

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Compliant | All 28 routes use `@role_required()` |
| Access Control Model | Compliant | DM role + project/project_site scope |
| CSRF Protection | Compliant | All mutating endpoints protected by CSRFProtect |
| Rate Limiting | Compliant | Exports and MV refresh rate-limited |

## Findings

None. Comprehensive auth, ABAC, rate limiting, and CSRF coverage across all 28 routes.
