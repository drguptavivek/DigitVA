---
title: "Route & Access Audit Index"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# Route & Access Audit

Per-blueprint audit of every route's authentication, authorization (role), and scoping (project/site) enforcement.

## Audit Files

| # | Blueprint | File | Routes | Key Findings |
|---|-----------|------|--------|--------------|
| 01 | health | [01-health.md](01-health.md) | 1 | Clean. Public health check, rate-limit exempt. |
| 02 | va_main | [02-va-main.md](02-va-main.md) | 3 | Clean. Public landing page aliases. |
| 03 | va_auth | [03-va-auth.md](03-va-auth.md) | 2 | Clean. Login rate-limited 10/min, open-redirect protection. |
| 04 | profile | [04-profile.md](04-profile.md) | 7 | Clean. Self-scoped, password changes rate-limited. |
| 05 | coding | [05-coding.md](05-coding.md) | 16 | 2 findings: implicit coder check on `/pick`; hardcoded TR01 date filter. |
| 06 | reviewing | [06-reviewing.md](06-reviewing.md) | 7 | 1 finding: `/start` delegates auth to service layer. |
| 07 | sitepi | [07-sitepi.md](07-sitepi.md) | 2 | 1 finding: inline HTML error instead of proper 403 on `/data`. |
| 08 | data_management | [08-data-management.md](08-data-management.md) | 28 | 2 findings: audit log in GET handler; analytics routes are DM-only. |
| 09 | va_form | [09-va-form.md](09-va-form.md) | 3 (compound) | 3 findings: large function; deprecated media route; defense-in-depth role check. |
| 10 | admin | [10-admin.md](10-admin.md) | 90+ | 2 findings: activity log admin-only; very large blueprint file. |
| 11 | api_v1 shared | [11-api-v1-shared.md](11-api-v1-shared.md) | 4 | 2 findings: duplicated `_require_coding_access()`; ICD-10 has no rate limit. |

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total blueprints audited | 11 |
| Total route handlers | ~170 |
| Routes without authentication | 5 (health, index pages, login) |
| Routes with role-based access | ~165 |
| Admin-only routes | ~70 |
| Admin + Project PI routes | ~15 |
| Data Manager routes | ~30 |
| Coder routes | ~25 |
| Reviewer routes | ~7 |
| Site PI routes | 2 |
| Any authenticated routes | ~10 (profile, ICD-10, workflow events) |

## Auth Mechanism Summary

| Layer | Mechanism | Applies To |
|-------|-----------|------------|
| **Session Auth** | Flask-Login `@login_required` | All workflow routes |
| **Session Auth (manual)** | `_request_user()` reads session | Admin API routes |
| **Session Auth (manual)** | `current_user.is_authenticated` | Attachment serving |
| **Role Decorator** | `@require_api_role(...)` | Admin API routes |
| **Permission Decorator** | `@va_validate_permissions()` | Form partial rendering |
| **Inline Role Check** | `current_user.is_coder()` etc. | Page routes (coding, reviewing, etc.) |
| **UI Access Guard** | `_require_admin_ui_access()` | Admin panel HTML routes |
| **CSRF** | Flask-WTF `X-CSRFToken` | All mutating browser requests |
| **Rate Limiting** | Flask-Limiter | Login (10/min), password (5/min), exports (30/min), general (2000/day) |

## Scoping Summary

| Role | Scope Type | Enforcement Pattern |
|------|-----------|-------------------|
| `admin` | `global` | Bypasses all scope checks; full access |
| `project_pi` | `project` | Admin API filters by `get_project_pi_projects()`; cannot manage admin/pi grants |
| `site_pi` | `project_site` | `get_site_pi_sites()` returns assigned site IDs; per-site filtering on dashboard |
| `data_manager` | `project` or `project_site` | `get_data_manager_projects()` + `get_data_manager_project_sites()`; MV-based analytics scoping |
| `coder` | `project` or `project_site` | `get_coder_va_forms()` returns form IDs; language filter; allocation ownership |
| `reviewer` | `project` or `project_site` | `get_reviewer_va_forms()` returns form IDs; language filter; allocation ownership |
| `collaborator` | `project` or `project_site` | Grant exists but no dedicated routes yet |

## Cross-Cutting Findings

1. **No `collaborator`-role routes exist.** The role is defined in the access control model and grant system, but no routes currently serve `collaborator` users. They would currently fall through to permission-denied on all workflow routes.

2. **`site_pi` dashboard is the only site_pi-specific surface.** Site PIs view data through their dashboard. They cannot open individual submission forms through the standard workflow routes (the `va_form` blueprint does handle `vasitepi` action type via the decorator).

3. **Auth patterns are inconsistent between blueprints.** Admin uses `@require_api_role()` + `_request_user()`. Coding/reviewing/DM use `@login_required` + inline role checks. Profile uses `@login_required` with no role check. This is functionally correct but makes the codebase harder to audit mechanically.

4. **Admin blueprint is disproportionately large** (~5057 lines). Consider extracting service classes for ODK connections, sync operations, and field mapping CRUD.
