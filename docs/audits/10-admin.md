---
title: "Route Audit — admin Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-19
---

# admin Blueprint Audit

**File:** `app/routes/admin.py`
**URL Prefix:** `/admin`
**Registration:** `app.register_blueprint(admin, url_prefix="/admin")`

This is the largest blueprint (~4900 lines, ~94 routes). Routes are split into:
1. **Admin API routes** (`/admin/api/...`) — JSON, gated by `@role_required()`
2. **Admin UI panel routes** (`/admin/panels/...`) — HTML, gated by `@role_required()`
3. **Field mapping routes** — Admin-only configuration

## API Routes — Bootstrap & Configuration

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 1 | GET | `/admin/api/bootstrap` | `@role_required("admin","project_pi")` | admin, project_pi | Scoped to user's projects | No |

## API Routes — Projects CRUD

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 2 | GET | `/admin/api/projects` | `@role_required("admin","project_pi")` | admin, project_pi | PI: own projects only | No |
| 3 | POST | `/admin/api/projects` | `@role_required("admin")` | admin only | Global | Yes |
| 4 | PUT | `/admin/api/projects/<id>` | `@role_required("admin")` | admin only | Global | Yes |
| 5 | POST | `/admin/api/projects/<id>/toggle` | `@role_required("admin")` | admin only | Global | Yes |

## API Routes — Sites CRUD

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 6 | GET | `/admin/api/sites` | `@role_required("admin","project_pi")` | admin, project_pi | PI: sites in own projects | No |
| 7 | POST | `/admin/api/sites` | `@role_required("admin")` | admin only | Global | Yes |
| 8 | PUT | `/admin/api/sites/<id>` | `@role_required("admin")` | admin only | Global | Yes |
| 9 | POST | `/admin/api/sites/<id>/toggle` | `@role_required("admin")` | admin only | Global | Yes |

## API Routes — Project-Site Mappings

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 10 | GET | `/admin/api/project-sites` | `@role_required("admin","project_pi")` | admin, project_pi | `_current_user_can_manage_project()` | No |
| 11 | POST | `/admin/api/project-sites` | `@role_required("admin","project_pi")` | admin, project_pi | `_current_user_can_manage_project()` | Yes |
| 12 | POST | `/admin/api/project-sites/<uuid>/toggle` | `@role_required("admin","project_pi")` | admin, project_pi | `_current_user_can_manage_project()` | Yes |

## API Routes — Users CRUD

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 13 | GET | `/admin/api/users` | `@role_required("admin","project_pi")` | admin, project_pi | PI: active users only | No |
| 14 | POST | `/admin/api/users` | `@role_required("admin")` | admin only | Global | Yes |
| 15 | PUT | `/admin/api/users/<uuid>` | `@role_required("admin")` | admin only | Global | Yes |
| 16 | POST | `/admin/api/users/<uuid>/toggle` | `@role_required("admin")` | admin only | Global | Yes |

## API Routes — Access Grants

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 17 | GET | `/admin/api/access-grants` | `@role_required("admin","project_pi")` | admin, project_pi | `_project_access_filter()` | No |
| 18 | GET | `/admin/api/access-grants/orphaned` | `@role_required("admin","project_pi")` | admin, project_pi | `_project_access_filter()` | No |
| 19 | POST | `/admin/api/access-grants` | `@role_required("admin","project_pi")` | admin, project_pi | PI: cannot manage admin/pi grants | Yes |
| 20 | POST | `/admin/api/access-grants/<uuid>/toggle` | `@role_required("admin","project_pi")` | admin, project_pi | PI: cannot toggle admin/pi grants | Yes |

## API Routes — ODK Connections

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 21 | GET | `/admin/api/odk-connections` | `@role_required("admin")` | admin | Global | No |
| 22 | POST | `/admin/api/odk-connections` | `@role_required("admin")` | admin | Global | Yes |
| 23 | PUT | `/admin/api/odk-connections/<uuid>` | `@role_required("admin")` | admin | Global | Yes |
| 24 | POST | `/admin/api/odk-connections/<uuid>/toggle` | `@role_required("admin")` | admin | Global | Yes |
| 25 | POST | `/admin/api/odk-connections/<uuid>/test` | `@role_required("admin")` | admin | Global | No |
| 26 | GET | `/admin/api/odk-connections/<uuid>/odk-projects` | `@role_required("admin")` | admin | Global | No |
| 27 | GET | `/admin/api/odk-connections/<uuid>/odk-projects/<int>/forms` | `@role_required("admin")` | admin | Global | No |
| 28 | GET | `/admin/api/odk-connections/<uuid>/projects` | `@role_required("admin")` | admin | Global | No |
| 29 | POST | `/admin/api/odk-connections/<uuid>/assign-project` | `@role_required("admin")` | admin | Global | Yes |
| 30 | DELETE | `/admin/api/odk-connections/<uuid>/assign-project/<id>` | `@role_required("admin")` | admin | Global | Yes |

## API Routes — Sync Operations

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 31 | GET | `/admin/api/sync/status` | `@role_required("admin")`, `@limiter.exempt` | admin | Global | No |
| 32 | GET | `/admin/api/sync/history` | `@role_required("admin")`, `@limiter.exempt` | admin | Global | No |
| 33 | POST | `/admin/api/sync/trigger` | `@role_required("admin")` | admin | Global | Yes |
| 34 | POST | `/admin/api/sync/stop` | `@role_required("admin")` | admin | Global | Yes |
| 35 | POST | `/admin/api/sync/schedule` | `@role_required("admin")` | admin | Global | Yes |
| 36 | GET | `/admin/api/sync/coverage` | `@role_required("admin")` | admin | Global | No |
| 37 | GET | `/admin/api/sync/backfill-stats` | `@role_required("admin")`, `@limiter.exempt` | admin | Global | No |
| 38 | POST | `/admin/api/sync/backfill/form/<form_id>` | `@role_required("admin")` | admin | Global | Yes |
| 39 | POST | `/admin/api/sync/form/<form_id>` | `@role_required("admin")` | admin | Global | Yes |
| 40 | POST | `/admin/api/sync/project-site/<id>/<id>` | `@role_required("admin")` | admin | Global | Yes |
| 41 | GET | `/admin/api/sync/revoked-stats` | `@role_required("admin")`, `@limiter.exempt` | admin | Global | No |
| 42 | GET | `/admin/api/sync/progress` | `@role_required("admin")`, `@limiter.exempt` | admin | Global | No |

## API Routes — Field Mapping

| # | Method | Path | Decorator | Roles | Mutates |
|---|--------|------|-----------|-------|---------|
| 46 | GET | `/admin/api/form-types` | `@role_required("admin")` | admin | No |
| 47 | POST | `/admin/api/form-types` | `@role_required("admin")` | admin | Yes |
| 48 | PATCH | `/admin/api/form-types/<code>` | `@role_required("admin")` | admin | Yes |
| 49 | POST | `/admin/api/form-types/<code>/duplicate` | `@role_required("admin")` | admin | Yes |
| 50 | GET | `/admin/api/form-types/<code>/export` | `@role_required("admin")` | admin | No |
| 51 | POST | `/admin/api/form-types/import` | `@role_required("admin")` | admin | Yes |
| 52 | GET | `/admin/api/form-types/<code>/categories/<code>/subcategories` | `@role_required("admin")` | admin | No |
| 53 | GET | `/admin/api/form-types/<code>/categories/<code>/browser-state` | `@role_required("admin")` | admin | No |
| 54 | POST | `/admin/api/form-types/<code>/categories/<code>/fields/reorder` | `@role_required("admin")` | admin | Yes |
| 55 | POST | `/admin/api/form-types/<code>/fields/<field_id>/move` | `@role_required("admin")` | admin | Yes |
| 56 | GET | `/admin/api/form-types/<code>/fields/search` | `@role_required("admin")` | admin | No |
| 57 | POST | `/admin/api/form-types/<code>/categories` | `@role_required("admin")` | admin | Yes |
| 58 | PUT | `/admin/api/form-types/<code>/categories/<code>` | `@role_required("admin")` | admin | Yes |
| 59 | DELETE | `/admin/api/form-types/<code>/categories/<code>` | `@role_required("admin")` | admin | Yes |
| 60 | POST | `/admin/api/form-types/<code>/categories/<code>/subcategories` | `@role_required("admin")` | admin | Yes |
| 61 | PUT | `/admin/api/form-types/<code>/categories/<code>/subcategories/<code>` | `@role_required("admin")` | admin | Yes |
| 62 | DELETE | `/admin/api/form-types/<code>/categories/<code>/subcategories/<code>` | `@role_required("admin")` | admin | Yes |

## API Routes — Languages

| # | Method | Path | Decorator | Roles | Mutates |
|---|--------|------|-----------|-------|---------|
| 63 | GET | `/admin/api/languages` | `@role_required("admin")` | admin | No |
| 64 | POST | `/admin/api/languages` | `@role_required("admin")` | admin | Yes |
| 65 | PUT | `/admin/api/languages/<code>` | `@role_required("admin")` | admin | Yes |
| 66 | POST | `/admin/api/languages/<code>/toggle` | `@role_required("admin")` | admin | Yes |
| 67 | DELETE | `/admin/api/languages/<code>/aliases/<alias>` | `@role_required("admin")` | admin | Yes |

## API Routes — Project ODK Mappings

| # | Method | Path | Decorator | Roles | Mutates |
|---|--------|------|-----------|-------|---------|
| 68 | GET | `/admin/api/projects/<id>/odk-connection` | `@role_required("admin")` | admin | No |
| 69 | GET | `/admin/api/projects/<id>/odk-site-mappings` | `@role_required("admin")` | admin | No |
| 70 | POST | `/admin/api/projects/<id>/odk-site-mappings` | `@role_required("admin")` | admin | Yes |
| 71 | DELETE | `/admin/api/projects/<id>/odk-site-mappings/<site>` | `@role_required("admin")` | admin | Yes |

## UI Panel Routes (`/admin/panels/`)

| # | Method | Path | Decorator | Roles | Notes |
|---|--------|------|-----------|-------|-------|
| 72 | GET | `/admin/` | `@role_required("admin","project_pi")` | admin, project_pi | SPA shell |
| 73 | GET | `/admin/panels/access-grants` | `@role_required("admin","project_pi")` | admin, project_pi | |
| 74 | GET | `/admin/panels/project-sites` | `@role_required("admin","project_pi")` | admin, project_pi | |
| 75 | GET | `/admin/panels/project-forms` | `@role_required("admin")` | admin | |
| 76 | GET | `/admin/panels/projects` | `@role_required("admin")` | admin | |
| 77 | GET | `/admin/panels/sites` | `@role_required("admin")` | admin | |
| 78 | GET | `/admin/panels/users` | `@role_required("admin")` | admin | |
| 79 | GET | `/admin/panels/project-pi` | `@role_required("admin")` | admin | |
| 80 | GET | `/admin/panels/languages` | `@role_required("admin")` | admin | |
| 81 | GET | `/admin/panels/odk-connections` | `@role_required("admin")` | admin | |
| 82 | GET | `/admin/panels/field-mapping` | `@role_required("admin")` | admin | |
| 83 | GET | `/admin/panels/field-mapping/fields` | `@role_required("admin")` | admin | |
| **84** | GET,POST | `/admin/panels/field-mapping/field/<code>/<id>` | **None** | Inline `is_admin()` only | **See F1** |
| 85 | PATCH | `/admin/panels/field-mapping/field/<code>/<id>/category` | `@role_required("admin")` | admin | |
| 86 | PATCH | `/admin/panels/field-mapping/field/<code>/<id>/order` | `@role_required("admin")` | admin | |
| 87 | GET | `/admin/panels/field-mapping/categories` | `@role_required("admin")` | admin | |
| 88 | GET | `/admin/panels/field-mapping/choices` | `@role_required("admin")` | admin | |
| 89 | GET | `/admin/panels/field-mapping/sync` | `@role_required("admin")` | admin | |
| 90 | POST | `/admin/panels/field-mapping/sync/preview` | `@role_required("admin")` | admin | |
| 91 | POST | `/admin/panels/field-mapping/sync/apply` | `@role_required("admin")` | admin | |
| 92 | POST | `/admin/panels/field-mapping/sync` | `@role_required("admin")` | admin | |
| **93** | GET | `/admin/panels/sync` | **None** | Inline `is_admin()` only | **See F1** |
| **94** | GET | `/admin/panels/activity` | **None** | Inline `is_admin()` only | **See F1** |

## Scoping Details

### Project PI Scoping on API Routes
- **Read operations:** PI sees only projects in `get_project_pi_projects()`
- **Write operations:** PI can create/toggle project-sites and grants within their projects
- **Grant restrictions:** PI cannot manage `admin` or `project_pi` grants
- **Cross-project protection:** `_current_user_can_manage_project()` validates project ownership

### Admin Bypass
- Admin users (`@role_required("admin")`) have global access
- Some admin-only routes have redundant inline `is_admin()` checks after `@role_required("admin")` — harmless artifact from before standardization

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Partial | 91/94 routes use `@role_required()`. 3 routes use inline checks |
| Access Control Model | Compliant | Admin = global; PI = project-scoped |
| CSRF Protection | Compliant | CSRFProtect enforced on all mutating routes |
| PII Protection | Compliant | ODK credentials encrypted; never serialized in responses |

## Findings

1. **F1 — Three routes missing `@role_required()` decorator (routes 84, 93, 94).** `admin_panel_field_mapping_field_edit`, `admin_panel_sync`, and `admin_panel_activity` use inline `is_admin()` checks instead of `@role_required()`. This skips the active-status gate — a deactivated user with a valid session could reach the inline check (which would return 403, but without triggering `logout_user()`). **Severity: Medium** — should be migrated to `@role_required("admin")`.

2. **F2 — Redundant inline `is_admin()` checks on 12+ routes.** Routes 3–5, 7–9, 14–16, and 92 have `@role_required("admin")` AND an inline `is_admin()` guard. The decorator already enforces admin access. **Severity: Info** — harmless but noisy. Cleanup candidate.

3. **F3 — Activity log (route 94) is admin-only.** PI users cannot see the activity log even for their own projects. May be intentional but worth confirming against policy. **Severity: Info**.
