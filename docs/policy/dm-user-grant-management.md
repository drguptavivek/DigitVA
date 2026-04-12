---
title: Data-Manager User and Grant Management Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-04-12
---

# Data-Manager User and Grant Management Policy

## Purpose

Data-managers may create users and manage coder, coding-tester, and
data-manager grants within their own scope, without requiring admin or
project-PI intervention.

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
| `/data-management/api/access-grants` | GET | List coder/coding_tester/data_manager grants in scope |
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
- `coding_tester`
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
2. The role must be `coder`, `coding_tester`, or `data_manager`.
3. The scope must fall within the data-manager's own grant scope.
4. If an inactive grant with the same user + role + scope already exists, it
   must be reactivated rather than creating a duplicate.
5. The grant status must be set to `active`.

### Toggle (activate / deactivate)

A data-manager may toggle grants that:

- have role `coder`, `coding_tester`, or `data_manager`
- fall within their scope
- are not the current user's own `data_manager` grant

A data-manager may **not** toggle grants with other roles or grants outside
their scope. They also may not revoke their own `data_manager` grant through
this interface.

## User Creation

A data-manager may create new users. Created users:

- receive status `active`
- must provide `email` and matching `email_confirm`
- are created in invite mode (no operator-entered password)
- receive both verification and password-setup emails; the password-setup email uses invite wording ("set your password") instead of reset wording
- when they verify their email for the first time, they are redirected to the password setup page
- after password setup, first login shows a terms-and-conditions-only gate
- start with `pw_reset_t_and_c=False` so onboarding gate remains in effect
- must have at least one VA language selected
- receive `landing_page="coder"` by default

Creating a user through this interface also requires an initial grant payload:

- project selection first (project must be in DM-manageable scope)
- role: `coder`, `coding_tester`, or `data_manager`
- scope: `project_site` for site-scoped DMs, `project_site` or `project` for
  project-scoped DMs
- target site/project must be inside the DM's own manageable scope

## Visibility

### Grant listing

Data-managers see only:

- grants with role `coder`, `coding_tester`, or `data_manager`
- grants within their own scope (project or project-site)

They do not see `admin`, `project_pi`, `site_pi`, `reviewer`, or `collaborator`
grants, even within their scope.

From the user-details modal, a `Manage Grants` action navigates to the grants
tab and pre-applies the selected user's email as the grants-table text filter.
It also preselects that user in the new-grant form.

### User listing

Data-managers may search users (up to 25 results) and open per-user details.
The details panel includes:

- account status (`active` / `deactive`)
- email verification status
- user VA language list
- in-scope active grant breakdown by:
  - project-level grants
  - project-site-level grants
- resend verification action (for unverified users)
- email update action only for users created by the same data-manager
- language update action for data-managers/admins
- a `Manage Grants` action that opens the grants tab focused on that user

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
