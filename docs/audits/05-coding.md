---
title: "Route Audit — coding Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# coding Blueprint Audit

**Files:**
- Page routes: `app/routes/coding.py` (`/coding/`)
- API routes: `app/routes/api/coding.py` (`/api/v1/coding/`)

## Page Routes (`/coding/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 1 | GET | `/coding/` | `@login_required` | `coder` or `admin` | `coder`: form grants; `admin`: global | No |
| 2 | GET | `/coding/start` | `@login_required` | `coder` | Form grants (scoped by project) | Yes (allocates) |
| 3 | GET | `/coding/resume` | `@login_required` | `coder` or `admin` | Active allocation ownership | No |
| 4 | GET | `/coding/pick/<va_sid>` | `@login_required` | `coder` (implicit via service) | Form grants | Yes (allocates) |
| 5 | GET | `/coding/recode/<va_sid>` | `@login_required` | `coder` | Form grants + recode window | Yes (allocates) |
| 6 | GET | `/coding/demo` | `@login_required` | `admin` only | Global | Yes (allocates) |
| 7 | GET | `/coding/view/<va_sid>` | `@login_required` | `coder` (form access) | Form grants | No |

## API Routes (`/api/v1/coding/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 8 | GET | `/api/v1/coding/allocation` | `@login_required` | Any (returns null if none) | Self allocation | No |
| 9 | POST | `/api/v1/coding/allocation` | `@login_required` | `coder` or `admin` (demo) | Form grants / global | Yes |
| 10 | POST | `/api/v1/coding/recode/<va_sid>` | `@login_required` | `coder` | Form grants + recode window | Yes |
| 11 | POST | `/api/v1/coding/admin-override-recode/<va_sid>` | `@login_required` | `admin` only | Global | Yes |
| 12 | POST | `/api/v1/coding/reviewer-eligible-after-recode-window` | `@login_required` | `admin` only | Global | Yes |
| 13 | GET | `/api/v1/coding/available` | `@login_required` | `coder` or `admin` | Form grants | No |
| 14 | GET | `/api/v1/coding/stats` | `@login_required` | `coder` or `admin` | Form grants | No |
| 15 | GET | `/api/v1/coding/history` | `@login_required` | `coder` or `admin` | Form grants | No |
| 16 | GET | `/api/v1/coding/projects` | `@login_required` | `coder` or `admin` | Form grants | No |

## Scoping Details

### Coder Scoping
- **Form-level:** `current_user.get_coder_va_forms()` returns set of `va_form_id` values the user has coder grants for
- **Language filter:** Submissions filtered by `current_user.vacode_language`
- **Project filter:** Optional `project_id` query param further narrows scope
- **Grant resolution:** `coder` grants at `project` scope expand to all sites; `project_site` grants are specific

### Admin Bypass
- Admin users (`current_user.is_admin()`) bypass coder scope checks on dashboards
- Admin can start demo coding sessions (`/coding/demo`, POST `allocation` with `demo: true`)
- Admin can override finalized submissions to `ready_for_coding` (`admin-override-recode`)
- Admin can trigger reviewer-eligible transitions (`reviewer-eligible-after-recode-window`)

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | Coder role + form-grant scope enforced |
| CSRF Protection | Compliant | All mutating API calls use session + CSRF |
| Coding Workflow State Machine | Compliant | Allocation service enforces workflow states |
| Demo Coding Retention | Compliant | Demo allocations flagged with `vademo_start_coding` |

## Findings

1. **`/coding/pick/<va_sid>` (route 4) lacks explicit coder role check at the route level.** The role check happens inside `allocate_pick_form()` service. This is acceptable if the service always validates, but differs from `/coding/start` which checks `is_coder()` at the route level. **Risk: Low** — service-layer enforcement is present.

2. **Temporary TR01 date filter** (coding.py:74-102) — hardcoded `datetime(2025, 9, 9)` cutoff for `UNSW01TR0101`. This is a site-specific operational hack embedded in route code. **Should be removed or moved to configuration when no longer needed.**
