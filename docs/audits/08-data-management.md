---
title: "Route Audit — data_management Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# data_management Blueprint Audit

**Files:**
- Page routes: `app/routes/data_management.py` (`/data-management/`)
- API routes: `app/routes/api/data_management.py` (`/api/v1/data-management/`)
- Analytics API: `app/routes/api/analytics.py` (`/api/v1/analytics/`)

## Page Routes (`/data-management/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 1 | GET | `/data-management/` | `@login_required` | `data_manager` | Project or project-site grants | No |
| 2 | GET | `/data-management/view/<va_sid>` | `@login_required` | `data_manager` | Project or project-site grants (checked per submission) | No (audit read) |
| 3 | GET | `/data-management/submissions/<va_sid>/odk-edit` | `@login_required` | `data_manager` | Per-submission DM access | Yes (redirect) |

## API Routes (`/api/v1/data-management/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 4 | GET | `/api/v1/data-management/submissions` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 5 | GET | `/api/v1/data-management/submissions/export.csv` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 6 | GET | `/api/v1/data-management/submissions/export-smartva-input.csv` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 7 | GET | `/api/v1/data-management/submissions/export-smartva-results.csv` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 8 | GET | `/api/v1/data-management/submissions/export-smartva-likelihoods.csv` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 9 | GET | `/api/v1/data-management/kpi` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 10 | GET | `/api/v1/data-management/filter-options` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 11 | GET | `/api/v1/data-management/submissions/<va_sid>/upstream-change-details` | `@login_required` | `data_manager` or `admin` | Per-submission DM/admin access | No |
| 12 | POST | `/api/v1/data-management/forms/<form_id>/sync` | `@login_required` | `data_manager` | Form-in-scope check | Yes (triggers sync) |
| 13 | POST | `/api/v1/data-management/sync/preview` | `@login_required` | `data_manager` | Scoped forms | No |
| 14 | GET | `/api/v1/data-management/sync/runs` | `@login_required` | `data_manager` | Scoped forms (filtered) | No |
| 15 | GET | `/api/v1/data-management/project-site-submissions` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 16 | POST | `/api/v1/data-management/submissions/<va_sid>/sync` | `@login_required` | `data_manager` | Per-submission DM access | Yes (triggers refresh) |
| 17 | POST | `/api/v1/data-management/submissions/<va_sid>/accept-upstream-change` | `@login_required` | `data_manager` or `admin` | Per-submission access | Yes (workflow) |
| 18 | POST | `/api/v1/data-management/submissions/<va_sid>/reject-upstream-change` | `@login_required` | `data_manager` or `admin` | Per-submission access | Yes (workflow) |
| 19 | POST | `/api/v1/data-management/submissions/<va_sid>/screening-pass` | `@login_required` | `data_manager` or `admin` | Per-submission access | Yes (workflow) |
| 20 | POST | `/api/v1/data-management/submissions/<va_sid>/screening-reject` | `@login_required` | `data_manager` or `admin` | Per-submission access | Yes (workflow) |

## Analytics API (`/api/v1/analytics/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 21 | GET | `/api/v1/analytics/kpi` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 22 | GET | `/api/v1/analytics/submissions/by-date` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 23 | GET | `/api/v1/analytics/submissions/by-week` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 24 | GET | `/api/v1/analytics/submissions/by-month` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 25 | GET | `/api/v1/analytics/demographics` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 26 | GET | `/api/v1/analytics/workflow` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 27 | GET | `/api/v1/analytics/cod` | `@login_required` | `data_manager` | Project/project-site grants | No |
| 28 | POST | `/api/v1/analytics/mv/refresh` | `@login_required` | `data_manager` | N/A | Yes (MV refresh) |

## Scoping Details

### Data Manager Scoping
- **Grant resolution:**
  - `get_data_manager_projects()` — project-level grants
  - `get_data_manager_project_sites()` — project-site-level grants as `(project_id, site_id)` tuples
- **Scope enforcement:**
  - Dashboard queries filter by both project and project-site grants
  - Per-submission routes check `has_data_manager_submission_access(project_id, site_id)`
  - MV-based analytics use `_dm_scope_filter()` with expanded `(project_id, site_id)` pairs
- **Admin access:** Routes 11, 17-20 accept `data_manager` OR `admin` via `_require_data_manager_or_admin()`
- **Form-level scoping:** `dm_form_in_scope()` and `dm_scoped_forms()` enforce that sync/preview operations only target forms within the DM's scope

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | DM role + project/project_site scope enforced |
| Data Manager Workflow | Compliant | Cannot code, review, or submit COD |
| ODK Sync Policy | Compliant | Scoped sync triggers; upstream change resolution scoped |
| CSRF Protection | Compliant | All mutating endpoints use session + CSRF |
| PII in Exports | Partial | CSV exports use dashboard-scoped data; policy says PII fields should be omitted — implementation relies on service-layer filtering |

## Findings

1. **Route 2 (`/data-management/view/<va_sid>`) writes an audit log directly in the route handler** (lines 72-80). This is the only page route that writes to the DB in a GET handler. While it's a non-mutating read audit, it does a `db.session.commit()` on a GET request. **Risk: Low** — audit-only, no business mutation.

2. **Analytics routes (21-28) live in a separate `analytics` sub-blueprint** but are DM-scoped. They are not accessible to other roles (admin, site_pi). This may be intentional to keep analytics DM-specific. If other roles need analytics, separate routes or role expansion would be needed.

3. **`admin` access on upstream change routes (17-20) is appropriate** per the upstream data change policy in the coding workflow state machine.
