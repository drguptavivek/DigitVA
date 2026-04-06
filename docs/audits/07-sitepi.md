---
title: "Route Audit — sitepi Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# sitepi Blueprint Audit

**File:** `app/routes/sitepi.py`
**URL Prefix:** `/sitepi/`
**Registration:** `app.register_blueprint(sitepi, url_prefix="/sitepi")`

## Routes

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/sitepi/` | `@role_required("site_pi")` | `@role_required` | site_pi | `get_site_pi_sites()` | No |
| 2 | GET | `/sitepi/data` | `@role_required("site_pi")` | `@role_required` | site_pi | Site ID in `get_site_pi_sites()` set | No |

## Route Details

### 1. `GET /sitepi/` — `dashboard()`
- **Auth:** `@role_required("site_pi")`
- **ABAC:** `get_site_pi_sites()` scopes visible data to user's assigned sites
- **Returns:** Site PI dashboard HTML

### 2. `GET /sitepi/data` — `sitepi_data()`
- **Auth:** `@role_required("site_pi")`
- **ABAC:** Checks `site_id` is in `get_site_pi_sites()` — returns 403 via `va_permission_abortwithflash` if not
- **Returns:** JSON data for the requested site

## Scoping Details

- **Grant resolution:** `get_site_pi_sites()` returns set of site IDs from `site_pi` grants
- **Scope type:** Always `project_site`
- **Cross-site protection:** Route 2 validates `site_id` against user's granted sites

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Compliant | Both routes use `@role_required("site_pi")` |
| Access Control Model | Compliant | Site-scoped ABAC enforced |
| CSRF Protection | N/A | GET-only routes |

## Findings

None. The previous finding (inline HTML error returning HTTP 200) was fixed in the auth standardization commit — now uses `va_permission_abortwithflash` + proper 403.
