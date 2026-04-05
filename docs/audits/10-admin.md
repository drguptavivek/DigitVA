---
title: "Route Audit — admin Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# admin Blueprint Audit

**File:** `app/routes/admin.py`
**URL Prefix:** `/admin`

This is the largest blueprint. Routes are split into:
1. **Admin API routes** (`/admin/api/...`) — JSON, role-checked via `@require_api_role()`
2. **Admin UI panel routes** (`/admin/panels/...`) — HTML, role-checked via `_require_admin_ui_access()` or inline checks
3. **Field mapping routes** — Admin-only configuration

## API Routes — Project Management (`/admin/api/projects/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 1 | GET | `/admin/api/bootstrap` | `@require_api_role("admin","project_pi")` | admin, project_pi | Scoped to user's projects | No |
| 2 | GET | `/admin/api/projects` | `@require_api_role("admin","project_pi")` | admin, project_pi | PI: own projects only | No |
| 3 | POST | `/admin/api/projects` | `@require_api_role("admin")` | admin only | Global | Yes |
| 4 | PUT | `/admin/api/projects/<id>` | `@require_api_role("admin")` | admin only | Global | Yes |
| 5 | POST | `/admin/api/projects/<id>/toggle` | `@require_api_role("admin")` | admin only | Global | Yes |

## API Routes — Site Management (`/admin/api/sites/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 6 | GET | `/admin/api/sites` | `@require_api_role("admin","project_pi")` | admin, project_pi | PI: sites in own projects | No |
| 7 | POST | `/admin/api/sites` | `@require_api_role("admin")` | admin only | Global | Yes |
| 8 | PUT | `/admin/api/sites/<id>` | `@require_api_role("admin")` | admin only | Global | Yes |
| 9 | POST | `/admin/api/sites/<id>/toggle` | `@require_api_role("admin")` | admin only | Global | Yes |

## API Routes — Project-Site Mapping (`/admin/api/project-sites/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 10 | GET | `/admin/api/project-sites` | `@require_api_role("admin","project_pi")` | admin, project_pi | Scoped | No |
| 11 | POST | `/admin/api/project-sites` | `@require_api_role("admin","project_pi")` | admin, project_pi | PI: own projects only | Yes |
| 12 | POST | `/admin/api/project-sites/<uuid>/toggle` | `@require_api_role("admin","project_pi")` | admin, project_pi | PI: own projects only | Yes |

## API Routes — User Management (`/admin/api/users/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 13 | GET | `/admin/api/users` | `@require_api_role("admin","project_pi")` | admin, project_pi | Global | No |
| 14 | POST | `/admin/api/users` | `@require_api_role("admin")` | admin only | Global | Yes |
| 15 | PUT | `/admin/api/users/<uuid>` | `@require_api_role("admin")` | admin only | Global | Yes |
| 16 | POST | `/admin/api/users/<uuid>/toggle` | `@require_api_role("admin")` | admin only | Global | Yes |

## API Routes — Access Grants (`/admin/api/access-grants/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 17 | GET | `/admin/api/access-grants` | `@require_api_role("admin","project_pi")` | admin, project_pi | Scoped via `_project_access_filter` | No |
| 18 | GET | `/admin/api/access-grants/orphaned` | `@require_api_role("admin","project_pi")` | admin, project_pi | Scoped | No |
| 19 | POST | `/admin/api/access-grants` | `@require_api_role("admin","project_pi")` | admin, project_pi | PI: cannot manage admin/pi grants | Yes |
| 20 | POST | `/admin/api/access-grants/<uuid>/toggle` | `@require_api_role("admin","project_pi")` | admin, project_pi | PI: cannot toggle admin/pi grants | Yes |

## API Routes — ODK Connections (`/admin/api/odk-connections/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 21 | GET | `/admin/api/odk-connections` | `@require_api_role("admin")` | admin only | Global | No |
| 22 | POST | `/admin/api/odk-connections` | `@require_api_role("admin")` | admin only | Global | Yes |
| 23 | PUT | `/admin/api/odk-connections/<uuid>` | `@require_api_role("admin")` | admin only | Global | Yes |
| 24 | POST | `/admin/api/odk-connections/<uuid>/toggle` | `@require_api_role("admin")` | admin only | Global | Yes |
| 25 | POST | `/admin/api/odk-connections/<uuid>/test` | `@require_api_role("admin")` | admin only | Global | No |
| 26 | GET | `/admin/api/odk-connections/<uuid>/odk-projects` | `@require_api_role("admin")` | admin only | Global | No |
| 27 | GET | `/admin/api/odk-connections/<uuid>/odk-projects/<int>/forms` | `@require_api_role("admin")` | admin only | Global | No |
| 28 | GET | `/admin/api/odk-connections/<uuid>/projects` | `@require_api_role("admin")` | admin only | Global | No |
| 29 | POST | `/admin/api/odk-connections/<uuid>/assign-project` | `@require_api_role("admin")` | admin only | Global | Yes |
| 30 | DELETE | `/admin/api/odk-connections/<uuid>/assign-project/<id>` | `@require_api_role("admin")` | admin only | Global | Yes |

## API Routes — Sync Operations (`/admin/api/sync/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 31 | GET | `/admin/api/sync/status` | `@require_api_role("admin")` | admin only | Global | No |
| 32 | GET | `/admin/api/sync/history` | `@require_api_role("admin")` | admin only | Global | No |
| 33 | POST | `/admin/api/sync/trigger` | `@require_api_role("admin")` | admin only | Global | Yes |
| 34 | POST | `/admin/api/sync/attachment-backfill` | `@require_api_role("admin")` | admin only | Global | Yes |
| 35 | POST | `/admin/api/sync/stop` | `@require_api_role("admin")` | admin only | Global | Yes |
| 36 | POST | `/admin/api/sync/schedule` | `@require_api_role("admin")` | admin only | Global | Yes |
| 37 | GET | `/admin/api/sync/coverage` | `@require_api_role("admin")` | admin only | Global | No |
| 38 | GET | `/admin/api/sync/backfill-stats` | `@require_api_role("admin")` | admin only | Global | No |
| 39 | POST | `/admin/api/sync/backfill/form/<form_id>` | `@require_api_role("admin")` | admin only | Global | Yes |
| 40 | POST | `/admin/api/sync/trigger-smartva` | `@require_api_role("admin")` | admin only | Global | Yes |
| 41 | POST | `/admin/api/sync/form/<form_id>` | `@require_api_role("admin")` | admin only | Global | Yes |
| 42 | POST | `/admin/api/sync/project-site/<id>/<id>` | `@require_api_role("admin")` | admin only | Global | Yes |
| 43 | GET | `/admin/api/sync/smartva-stats` | `@require_api_role("admin")` | admin only | Global | No |
| 44 | GET | `/admin/api/sync/revoked-stats` | `@require_api_role("admin")` | admin only | Global | No |
| 45 | GET | `/admin/api/sync/progress` | `@require_api_role("admin")` | admin only | Global | No |

## API Routes — Field Mapping (`/admin/api/form-types/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 46-57 | CRUD | Various form-type/category/subcategory/field endpoints | `@require_api_role("admin")` | admin only | Global | Mixed |

## API Routes — Languages (`/admin/api/languages/`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 58-63 | CRUD | Language management endpoints | `@require_api_role("admin")` | admin only | Global | Mixed |

## API Routes — Project ODK Mappings (`/admin/api/projects/<id>/odk-*`)

| # | Method | Path | Decorator | Roles | Scope | Mutates |
|---|--------|------|-----------|-------|-------|---------|
| 64 | GET | `/admin/api/projects/<id>/odk-connection` | `@require_api_role("admin")` | admin only | Global | No |
| 65 | GET | `/admin/api/projects/<id>/odk-site-mappings` | `@require_api_role("admin")` | admin only | Global | No |
| 66 | POST | `/admin/api/projects/<id>/odk-site-mappings` | `@require_api_role("admin")` | admin only | Global | Yes |
| 67 | DELETE | `/admin/api/projects/<id>/odk-site-mappings/<site>` | `@require_api_role("admin")` | admin only | Global | Yes |

## UI Panel Routes (`/admin/panels/`)

| # | Method | Path | Auth Check | Admin Only | Notes |
|---|--------|------|------------|------------|-------|
| 68 | GET | `/admin/` | `_require_admin_ui_access()` | No (PI too) | Shell for admin SPA |
| 69 | GET | `/admin/panels/access-grants` | `_require_admin_ui_access()` | No (PI too) | |
| 70 | GET | `/admin/panels/project-sites` | `_require_admin_ui_access()` | No (PI too) | |
| 71 | GET | `/admin/panels/project-forms` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 72 | GET | `/admin/panels/projects` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 73 | GET | `/admin/panels/sites` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 74 | GET | `/admin/panels/users` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 75 | GET | `/admin/panels/project-pi` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 76 | GET | `/admin/panels/languages` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 77 | GET | `/admin/panels/odk-connections` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 78 | GET | `/admin/panels/field-mapping` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 79 | GET | `/admin/panels/field-mapping/fields` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 80 | GET | `/admin/panels/field-mapping/field/<code>/<id>` | `_require_admin_ui_access()` + `is_admin()` | Yes | GET/POST |
| 81 | PATCH | `/admin/panels/field-mapping/field/<code>/<id>/category` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 82 | PATCH | `/admin/panels/field-mapping/field/<code>/<id>/order` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 83 | GET | `/admin/panels/field-mapping/categories` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 84 | GET | `/admin/panels/field-mapping/choices` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 85 | GET | `/admin/panels/field-mapping/sync` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 86 | POST | `/admin/panels/field-mapping/sync/preview` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 87 | POST | `/admin/panels/field-mapping/sync/apply` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 88 | POST | `/admin/panels/field-mapping/sync` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 89 | GET | `/admin/panels/sync` | `_require_admin_ui_access()` + `is_admin()` | Yes | |
| 90 | GET | `/admin/panels/activity` | `_require_admin_ui_access()` + `is_admin()` | Yes | |

## Scoping Details

### `@require_api_role()` Decorator
- Uses `_request_user()` (reads from session, not `current_user`) to authenticate
- Checks `user_status == VaStatuses.active`
- Admin bypass: always allowed
- Project PI: allowed only if they have `get_project_pi_projects()` grants
- All other roles: denied

### `_require_admin_ui_access()` Helper
- Checks session-based user is authenticated and active
- Allows `admin` or any user with `get_project_pi_projects()` grants
- Redirects to login if not authenticated
- Returns 403 page if authenticated but no admin/PI role

### Project PI Scoping on API Routes
- **Read operations:** PI sees only projects in `get_project_pi_projects()`
- **Write operations:** PI can create/toggle project-sites and grants within their projects
- **Grant restrictions:** PI cannot manage `admin` or `project_pi` grants
- **Cross-project protection:** `_current_user_can_manage_project()` validates project ownership

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | Admin = global; PI = project-scoped |
| Admin API Access Policy | Compliant | Only admin and PI can access; PI scope restricted |
| CSRF Protection | Compliant | API routes use session + CSRF header |
| Grant Rules | Compliant | Explicit scope, idempotent, logical deactivation |
| PII Protection | Compliant | ODK credentials encrypted; never serialized in responses |

## Findings

1. **`_require_admin_ui_access()` does NOT use `@login_required`.** It manually reads the session to find the user. This works because admin panel routes need to redirect to login (not return 401). **Risk: None** — appropriate for HTML routes.

2. **Panel routes 72-90 (projects, sites, users, etc.) use inline `if not user.is_admin()` checks** after `_require_admin_ui_access()`. This means a PI user can access the admin index (route 68) but gets a 403 page when they navigate to admin-only panels. The API routes behind those panels are separately protected by `@require_api_role("admin")`. **Risk: None** — double-layered protection.

3. **The admin blueprint is very large** (~5057 lines). Most of this is route handlers with inline business logic. Many operations (ODK connection management, sync operations, field mapping CRUD) could be extracted to service classes for maintainability.

4. **Activity log (route 90) is admin-only.** PI users cannot see the activity log even for their own projects. This may be intentional but is worth confirming against policy requirements.
