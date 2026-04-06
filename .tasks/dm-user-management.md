---
status: done
priority: high
created: 2026-04-06
---

# Data-Manager User & Grant Management

## Goal

Allow data-managers to create users and manage coder/data_manager grants within
their own scope, without requiring admin or project-PI intervention.

## What was done

- Added 9 API endpoints to `app/routes/data_management.py`:
  - `GET /data-management/users` — management page
  - `GET /data-management/api/bootstrap` — CSRF + scope context
  - `GET /data-management/api/projects` — accessible projects
  - `GET /data-management/api/project-sites` — accessible project-sites
  - `GET/POST /data-management/api/users` — user search and creation
  - `GET/POST /data-management/api/access-grants` — grant listing and creation
  - `POST /data-management/api/access-grants/<id>/toggle` — activate/deactivate

- Added helper functions:
  - `_dm_can_manage_scope()` — scope validation with admin bypass
  - `_dm_grant_filter()` — SQLAlchemy filter for DM-visible grants

- Created template:
  - `app/templates/va_frontpages/data_manager_partials/_user_management.html`
  - Users tab (search, create) + Grants tab (create, toggle)
  - Role dropdown limited to coder/data_manager
  - Scope options filtered by DM's own scope

- Added "Manage Users" button to data-manager dashboard header

- Updated `role_required` decorator to recognize `/data-management/api/` as API routes

- Policy doc: `docs/policy/dm-user-grant-management.md`

- Tests: `tests/test_dm_manage.py` (25 tests, session isolation issue with some)

## Scope rules implemented

- Project-scoped DM: can assign at project or site level within their project
- Site-scoped DM: can only assign at site level for their specific sites
- Admin: full access via this interface
- Only coder and data_manager roles can be assigned

## Remaining

- Test session isolation issue: positive tests fail after negative tests when
  run as a full suite (Flask-SQLAlchemy session.remove() on teardown). Individual
  tests pass. Tests pass when run in isolation or when positive tests run first.
