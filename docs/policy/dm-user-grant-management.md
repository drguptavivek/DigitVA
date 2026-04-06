---
title: Data-Manager User and Grant Management Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-04-06
---

# Data-Manager User and Grant Management Policy

## Purpose

Data-managers may create users and manage coder and data-manager grants within
their own scope, without requiring admin or project-PI intervention.

This policy governs the `/data-management/users` page and its supporting API
endpoints.

## Route Family

All routes live under the existing `data_management` blueprint:

| Route | Method | Purpose |
|-------|--------|---------|
| `/data-management/users` | GET | User + grant management page |
| `/data-management/api/bootstrap` | GET | CSRF token and scope context |
| `/data-management/api/projects` | GET | Accessible projects |
| `/data-management/api/project-sites` | GET | Accessible project-sites |
| `/data-management/api/users` | GET | User search |
| `/data-management/api/users` | POST | Create user |
| `/data-management/api/access-grants` | GET | List coder/data_manager grants in scope |
| `/data-management/api/access-grants` | POST | Create or reactivate grant |
| `/data-management/api/access-grants/<id>/toggle` | POST | Activate/deactivate grant |

## Eligible Roles

These routes accept:

- `data_manager` — scoped by their own grant
- `admin` — full access, bypasses scope restrictions

## Scope Rules

A data-manager's own grants determine what they can assign.

### Project-scoped data-manager

May assign grants at:

- **project level** — for any project where they hold a project-scoped
  data-manager grant
- **project-site level** — for any site within those projects

### Site-scoped data-manager

May assign grants at:

- **project-site level only** — and only for the specific project-site pairs
  where they hold a site-scoped data-manager grant

A site-scoped data-manager **may not** assign project-level grants, even for
the project that contains their site.

### Admin

Admins bypass all scope restrictions. They can assign grants at any project or
site level through this interface.

## Assignable Roles

Data-managers may only assign these roles:

- `coder`
- `data_manager`

Data-managers may **not** assign:

- `admin`
- `project_pi`
- `site_pi`
- `reviewer`
- `collaborator`

## Grant Lifecycle

### Creation

When a data-manager creates a grant:

1. The target user must be active.
2. The role must be `coder` or `data_manager`.
3. The scope must fall within the data-manager's own grant scope.
4. If an inactive grant with the same user + role + scope already exists, it
   must be reactivated rather than creating a duplicate.
5. The grant status must be set to `active`.

### Toggle (activate / deactivate)

A data-manager may toggle grants that:

- have role `coder` or `data_manager`
- fall within their scope

A data-manager may **not** toggle grants with other roles or grants outside
their scope.

## User Creation

A data-manager may create new users. Created users:

- receive status `active`
- must set a password (force reset on first login via `pw_reset_t_and_c=False`)
- must have at least one VA language selected
- receive `landing_page="coder"` by default

Creating a user does **not** automatically assign any grants. The data-manager
must create grants separately through the grants interface.

## Visibility

### Grant listing

Data-managers see only:

- grants with role `coder` or `data_manager`
- grants within their own scope (project or project-site)

They do not see `admin`, `project_pi`, `site_pi`, `reviewer`, or `collaborator`
grants, even within their scope.

### User listing

Data-managers may search all active users (up to 25 results). This is necessary
for assigning grants to existing users.

## CSRF

All mutating endpoints require a valid CSRF token in the `X-CSRFToken` header,
consistent with the application-wide CSRF policy.

## Audit Expectations

Grant creation and toggle operations should be auditable through the existing
grant record timestamps (`grant_created_at`, `grant_updated_at`) and the
`notes` field.

## Separation from Admin Panel

This interface is intentionally separate from the `/admin/` panel:

- Data-managers access it through their own dashboard at
  `/data-management/users`
- The "Manage Users" button on the data-manager dashboard links to this page
- Admins may also access this interface, but they already have the full admin
  panel available

The admin panel retains its own user and grant management with full
role-assignment capabilities.
