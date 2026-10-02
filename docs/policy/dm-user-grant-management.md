---
title: Data-Manager User and Grant Management Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-02
---

# Data-Manager User and Grant Management Policy

## Purpose

Data-managers may create users and manage grants within their own scope,
without requiring admin or project-PI intervention. What they may grant
depends on the project's kind:

- **Site projects** (today's rule, unchanged): `coder`, `coding_tester` and
  `data_manager` grants at their own project or project-site scope.
- **District (organizational) projects** (decision 2026-10-02): other data
  managers strictly below their own level, and interviewer, coder, reviewer,
  coding-tester and viewer grants at any level of their subtree.

This policy governs the `/data-management/users` page and its supporting API
endpoints. The rule for who creates which grants is in
[Access Control Model](access-control-model.md), "Who creates which grants".
The district-project rule is implementation tracked in digitva-0wc; until it
lands the page applies the site-project rule in every project, plus
mentor-role unit grants for mentoring institute staff in a district the data
manager covers.

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
| `/data-management/api/access-grants` | GET | List the grants the data-manager may manage (see "Visibility") |
| `/data-management/api/access-grants` | POST | Create or reactivate a grant the data-manager may create |
| `/data-management/api/access-grants/<id>/toggle` | POST | Activate/deactivate a grant the data-manager may manage |

## Eligible Roles

These routes accept:

- `data_manager` — scoped by their own grant
- `admin` — full access, bypasses scope restrictions

In a district project the project PI and the in-charges also create
`data_manager` grants, under their own rules in
[Access Control Model](access-control-model.md), "Who creates which grants";
this page serves data managers and admins. Implementation tracked in
digitva-0wc.

## Scope Rules

A data-manager's own grants determine what they can assign.

### Site projects

Today's rule, unchanged.

#### Project-scoped data-manager

May assign grants at:

- **project level** — for any project where they hold a project-scoped
  data-manager grant
- **project-site level** — for any site within those projects

#### Site-scoped data-manager

May assign grants at:

- **project-site level only** — and only for the specific project-site pairs
  where they hold a site-scoped data-manager grant

A site-scoped data-manager **may not** assign project-level grants, even for
the project that contains their site.

#### Assignable roles (site projects)

Data-managers may only assign:

- `coder`
- `coding_tester`
- `data_manager`

Data-managers may **not** assign `admin`, `project_pi`, `site_pi`,
`reviewer`, `collaborator`, `collaborator_pii` or `interviewer`.

### District (organizational) projects

Decision 2026-10-02. Implementation tracked in digitva-0wc.

Each grant has a **subtree**: a `project` grant covers the whole project, a
`project_site` grant its (project, site) pair, an `org_unit` grant its unit
and every unit beneath it. One rule applies to every data manager of a
district project, whatever the scope of their grant:

- `data_manager` grants only **strictly below** their own grant, inside their
  subtree;
- `interviewer`, `coder`, `reviewer`, `coding_tester`, `collaborator` and
  `collaborator_pii` grants at **any level** inside their subtree, their own
  level included.

So a project-scoped data-manager assigns `data_manager` at project-site or
any unit level but never at project level; a unit-scoped data-manager assigns
`data_manager` only on units beneath their own unit; a site-scoped
data-manager assigns no `data_manager` grant, since nothing lies below a
project-site grant. Never on a unit above or outside their own.

Data-managers may **not** assign `admin`, `project_pi`, `site_pi`,
`interview_supervisor` or In-charge grants.

Cadre validation applies to every unit grant, and the mentor guard applies
when the grantee is a mentoring institute member (see
[Organization Model Policy](organization-model.md), "Unit-scoped grants" and
"Mentoring institutes").

### Admin

Admins bypass all scope restrictions. They can assign grants at any project or
site level through this interface.

## Grant Lifecycle

### Creation

When a data-manager creates a grant:

1. The target user must be active.
2. The role must be assignable for the project's kind (see "Scope Rules").
3. The scope must fall within the data-manager's own scope; in a district
   project, for `data_manager`, strictly below their own grant.
4. If an inactive grant with the same user + role + scope already exists, it
   must be reactivated rather than creating a duplicate.
5. The grant status must be set to `active`.

### Toggle (activate / deactivate)

A data-manager may toggle grants that:

- they could create under "Scope Rules" (role and scope both)
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
- role and scope: any the DM may assign under "Scope Rules" (site projects:
  `project_site` for site-scoped DMs, `project_site` or `project` for
  project-scoped DMs)
- target project, site or unit must be inside the DM's own scope

## Visibility

### Grant listing

A data-manager lists the grants they may manage under "Scope Rules", within
their own scope:

- site projects: `coder`, `coding_tester` and `data_manager` grants
- district projects (implementation tracked in digitva-0wc): grants of
  `interviewer`, `coder`, `reviewer`, `coding_tester`, `collaborator` and
  `collaborator_pii` anywhere inside their subtree, and `data_manager` grants
  strictly below their own
- for a mentoring institute member, the mentor grants inside a district they
  manage (see [Organization Model Policy](organization-model.md),
  "Mentoring institutes")

They do not see `admin`, `project_pi`, `site_pi`, `interview_supervisor` or
In-charge grants, nor any grant outside their scope.

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
  - unit-level grants (organizational projects)
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
