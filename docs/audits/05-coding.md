---
title: "Route Audit — coding Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# coding Blueprint Audit

**Files:**
- Page routes: `app/routes/coding.py` (`/coding/`)
- API routes: `app/routes/api/coding.py` (`/api/v1/coding/`)

## Page Routes (`/coding/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `get_coder_va_forms()` | No |
| 2 | POST | `/start` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `allocate_random_form()` | Yes (allocates) |
| 3 | GET | `/resume` | `@role_required("coder","admin")` | `@role_required` | coder, admin | Active allocation ownership | No |
| 4 | POST | `/pick/<va_sid>` | `@role_required("coder")` | `@role_required` | coder | `allocate_pick_form()` | Yes (allocates) |
| 5 | POST | `/recode/<va_sid>` | `@role_required("coder")` | `@role_required` | coder | `start_recode_allocation()` | Yes (allocates) |
| 6 | POST | `/demo` | `@role_required("admin")` | `@role_required` | admin | Global | Yes (allocates) |
| 7 | GET | `/view/<va_sid>` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `has_va_form_access()` | No |

## API Routes (`/api/v1/coding/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 8 | GET | `/api/v1/coding/allocation` | `@role_required("coder","admin")` | `@role_required` | coder, admin | Own active allocation | No |
| 9 | POST | `/api/v1/coding/allocation` | `@role_required("coder","admin")` | `@role_required` | coder, admin | Form grants / global | Yes |
| 10 | POST | `/api/v1/coding/recode/<va_sid>` | `@role_required("coder")` | `@role_required` | coder | Form grants + recode window | Yes |
| 11 | POST | `/api/v1/coding/admin-override-recode/<va_sid>` | `@role_required("admin")` | `@role_required` | admin | Global | Yes |
| 12 | POST | `/api/v1/coding/reviewer-eligible-after-recode-window` | `@role_required("admin")` | `@role_required` | admin | Global | Yes |
| 13 | GET | `/api/v1/coding/available` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `get_coder_va_forms()` | No |
| 14 | GET | `/api/v1/coding/stats` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `get_coder_va_forms()` | No |
| 15 | GET | `/api/v1/coding/history` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `get_coder_va_forms()` | No |
| 16 | GET | `/api/v1/coding/projects` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `get_coder_va_forms()` | No |

## Scoping Details

### Coder Scoping
- **Form-level:** `current_user.get_coder_va_forms()` returns set of `va_form_id` values the user has coder grants for
- **Language filter:** Submissions filtered by `current_user.vacode_language`
- **Project filter:** Optional `project_id` query param further narrows scope
- **Grant resolution:** `coder` grants at `project` scope expand to all sites; `project_site` grants are specific

### Admin Bypass
- Admin users bypass coder scope checks on dashboards
- Admin can start demo coding sessions (`/demo`, POST `allocation` with `demo: true`)
- Admin can override finalized submissions to `ready_for_coding` (`admin-override-recode`)
- Admin can trigger reviewer-eligible transitions (`reviewer-eligible-after-recode-window`)

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Compliant | All 16 routes use `@role_required()` |
| Access Control Model | Compliant | Coder role + form-grant scope enforced |
| CSRF Protection | Compliant | POST routes protected by CSRFProtect |
| Coding Workflow State Machine | Compliant | Allocation service enforces workflow states |
| Demo Coding Retention | Compliant | Demo allocations flagged with `vademo_start_coding` |

## Findings

1. ~~**F1 — Routes 2, 4, 5, 6 perform state-changing operations on GET.**~~ **Fixed**: Routes `/start`, `/pick`, `/recode`, `/demo` converted to POST with CSRF protection. Template links updated to inline forms with CSRF tokens. Also added "admin" to `/start` role_required per policy doc Section 6.

2. **F2 — Routes 2, 4, 5 delegate ABAC to service layer.** `/start`, `/pick`, `/recode` do not do explicit `has_va_form_access()` checks at the route level — enforcement is in `allocate_random_form()`, `allocate_pick_form()`, etc. Only `/view` (route 7) does an explicit inline check. **Severity: Info** — acceptable if services are the canonical enforcement point.

3. **F3 — `/start` accepts `project_id` from query string with no route-level access validation.** The `allocate_random_form` service function enforces this, but the route does not validate. **Severity: Low**.

4. **F4 — Demo project allocation has 5 pre-existing test failures.** `allocate_random_form` returns `None` for demo project forms. Service-layer issue — tests `test_demo_random_coding_*` and `test_demo_training_project_*` fail identically on clean HEAD. Not an RBAC issue. **Severity: Info** — tracked separately.
