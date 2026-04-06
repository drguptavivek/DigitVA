---
title: "Route & Access Audit Index"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# Route & Access Audit

Per-blueprint audit of every route's authentication, authorization (role), and scoping (project/site) enforcement.

**Post-standardization audit** — reflects state after commit `e12dd3a` (replaced ad-hoc auth helpers with `@role_required()` across all blueprints).

## Audit Files

| # | Blueprint | File | Routes | `@role_required` | Findings |
|---|-----------|------|--------|-------------------|----------|
| 01 | health | [01-health.md](01-health.md) | 1 | N/A (public) | 0 |
| 02 | va_main | [02-va-main.md](02-va-main.md) | 3 | N/A (public) | 0 |
| 03 | va_auth | [03-va-auth.md](03-va-auth.md) | 2 | N/A (pre-auth) | 2 |
| 04 | profile | [04-profile.md](04-profile.md) | 7 | 0 (all `@login_required`) | 2 |
| 05 | coding | [05-coding.md](05-coding.md) | 16 | 16 | 3 |
| 06 | reviewing | [06-reviewing.md](06-reviewing.md) | 7 | 7 | 0 |
| 07 | sitepi | [07-sitepi.md](07-sitepi.md) | 2 | 2 | 0 |
| 08 | data_management | [08-data-management.md](08-data-management.md) | 28 | 28 | 0 |
| 09 | va_form | [09-va-form.md](09-va-form.md) | 3 | 0 (manual/`@login_required`) | 3 |
| 10 | admin | [10-admin.md](10-admin.md) | ~94 | 91 | 3 |
| 11 | api_v1 shared | [11-api-v1-shared.md](11-api-v1-shared.md) | 4 | 2 | 4 |

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total blueprints audited | 11 |
| Total route handlers | ~167 |
| Routes with `@role_required()` | 146 (87%) |
| Routes with `@login_required` | 12 (7%) |
| Routes without authentication | 6 (public: health, index, login) |
| Routes missing `@role_required` that should have it | 3 (admin panels) |
| Total findings | 17 |

## Auth Mechanism Summary

| Layer | Mechanism | Applies To |
|-------|-----------|------------|
| **RBAC role gate** | `@role_required(*roles)` | 146 routes — coders, reviewers, DMs, admins, PIs, site PIs |
| **Session auth** | Flask-Login `@login_required` | 12 routes — profile, ICD-10, workflow events |
| **Workflow validator** | `@va_validate_permissions()` | va_form renderpartial (multi-role dispatch) |
| **Manual auth** | Inline `is_admin()` / `is_authenticated` | 4 routes — 3 admin panels + attachment serving |
| **CSRF** | Flask-WTF `CSRFProtect` (`X-CSRFToken` header) | All mutating browser requests — no exemptions |
| **Rate Limiting** | Flask-Limiter | Login (10/min), password (5/min), exports (30/min), MV refresh (1/min), demographics (120/min), general (2000/day) |

## Scoping Summary

| Role | Scope Type | Enforcement Pattern |
|------|-----------|-------------------|
| `admin` | `global` | Bypasses all scope checks; full access |
| `project_pi` | `project` | Admin API filters by `get_project_pi_projects()`; cannot manage admin/pi grants |
| `site_pi` | `project_site` | `get_site_pi_sites()` returns assigned site IDs; per-site filtering |
| `data_manager` | `project` or `project_site` | `get_data_manager_projects()` + `get_data_manager_project_sites()`; MV-based analytics scoping |
| `coder` | `project` or `project_site` | `get_coder_va_forms()` returns form IDs; language filter; allocation ownership |
| `reviewer` | `project` or `project_site` | `get_reviewer_va_forms()` returns form IDs; language filter; allocation ownership |
| `collaborator` | TBD | Grant exists but no routes currently serve this role |

## Cross-Cutting Findings

| # | Severity | Blueprint(s) | Description |
|---|----------|-------------|-------------|
| F1 | **Medium** | admin | 3 routes (field edit, sync panel, activity panel) missing `@role_required()` — use inline `is_admin()` instead, skipping active-status gate |
| F2 | **Medium** | va_form | `serve_attachment()` uses manual `is_authenticated` check — skips active-status gate |
| F3 | **Medium** | coding | 4 allocation routes (`/start`, `/pick`, `/recode`, `/demo`) use GET for state-changing operations — wrong HTTP semantics, no CSRF |
| F4 | Low | profile | All 7 routes use `@login_required` — skips active-status guard (self-scoped only) |
| F5 | Low | api.icd10, api.workflow | Use `@login_required` — inconsistent with `@role_required` standard |
| F6 | Low | va_auth | `/valogout` is GET-based — CSRF could force-logout |
| F7 | Info | admin | 12+ routes have redundant inline `is_admin()` after `@role_required("admin")` — cleanup candidate |
| F8 | Info | va_form | `renderpartial()` uses `@login_required` + `@va_validate_permissions()` — intentional multi-role dispatch |
| F9 | Info | coding | ABAC delegated to service layer in allocation routes — acceptable pattern |
| F10 | Info | api.icd10 | No rate limiting on wildcard LIKE search query |
| F11 | Info | — | `collaborator` role has no dedicated routes |

## Remediation Priority

1. ~~**3 admin panel routes** missing `@role_required()`~~ — **Fixed**: added `@role_required("admin")`, removed inline checks
2. ~~**`serve_attachment()`**~~ — **Fixed**: added `@role_required()` with all workflow roles
3. **4 coder allocation GET routes** — convert to POST for proper HTTP semantics and CSRF protection (requires template + test updates)
4. **Profile routes** — consider `@role_required()` with all workflow roles for active-status guard
