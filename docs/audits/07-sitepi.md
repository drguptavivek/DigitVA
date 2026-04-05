---
title: "Route Audit — sitepi Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# sitepi Blueprint Audit

**File:** `app/routes/sitepi.py`
**URL Prefix:** `/sitepi`

## Routes

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 1 | GET | `/sitepi/` | `@login_required` | `site_pi` | Project-site grants | No |
| 2 | GET | `/sitepi/data` | `@login_required` | `site_pi` | Project-site grants | No |

## Route Details

### 1. `GET /sitepi/` — `dashboard()`
- **Role check:** `current_user.is_site_pi()` — aborts 403 if no site_pi grants
- **Scope check:** `current_user.get_site_pi_sites()` — aborts 403 if empty
- **Renders:** Dashboard with first assigned site as default

### 2. `GET /sitepi/data` — `sitepi_data()`
- **Role check:** Implicit (only reaches here if logged in)
- **Scope check:** Explicit — `site_id` parameter must be in `current_user.get_site_pi_sites()`
- **Returns:** HTMX partial with dashboard data for selected site
- **Security:** Returns inline HTML error messages ("Access denied") rather than using `va_permission_abortwithflash` — inconsistent with other blueprints

## Scoping Details

### Site PI Scoping
- **Grant resolution:** `get_site_pi_sites()` returns set of site IDs the user has `site_pi` grants for
- **Scope type:** Always `project_site` (per policy, `site_pi` uses `project_site` scope only)
- **Dashboard data:** `get_sitepi_dashboard_data(site_id)` generates stats for one site
- **Cross-site protection:** Route 2 explicitly validates `site_id` against user's granted sites

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | `site_pi` role + `project_site` scope enforced |
| CSRF Protection | N/A | GET routes only |
| Read-only | Compliant | No mutation endpoints for site PI |

## Findings

1. **Route 2 (`/sitepi/data`) returns inline HTML error strings instead of using `va_permission_abortwithflash`.** This is inconsistent with the rest of the application's error handling pattern. The 403 is not a proper HTTP 403 — it returns 200 with a "Access denied" div. **Risk: Low** — HTMX partial, but should use proper error handling for consistency.

2. **No admin bypass.** Unlike other blueprints, there is no admin fallback. Admin users cannot view the site PI dashboard. This aligns with policy (admin has separate admin panel), but worth noting.
