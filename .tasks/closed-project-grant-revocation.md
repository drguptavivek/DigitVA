# Closed projects do not revoke project-scoped grants

- **Status**: done (2026-09-19)
- **Priority**: medium
- **Created**: 2026-09-19

## Decision

A project whose `va_project_master.project_status != active` resolves **no
grant of any scope** — `project`, `project_site` or `org_unit` — for any
non-admin role, in every mechanism.

Grants are **not** revoked: no row is deleted and no `grant_status` changes.
Reopening the project restores the same access, and the grant's audit history
is untouched. Admin bypass is unchanged (`admin` is a `global` grant and is
never grant-resolved against a project).

Rationale: the two mechanisms already assumed a closed project's grants were
revoked. Making that true at resolution time is the smallest change that makes
them agree. Revoking the rows would be a destructive rewrite of state that is
meant to be reversible.

## Implementation

One shared predicate, `app/services/org_grant_service.py::active_project_condition`,
ANDed into each resolver's own query as a correlated `EXISTS` on the project's
primary key — never a per-grant lookup. Applied in:

- `org_grant_service`: `_grant_units_stmt` (so `granted_units` /
  `granted_project_ids`), `scope_unit_ids`, `scope_unit_ids_for_roles`,
  `codeable_unit_ids`, and both branches of `project_wide_grant_exists`.
- `app/models/va_users.py`: `_get_granted_project_ids`,
  `_get_granted_project_site_pairs`, `_get_granted_va_forms` (one condition on
  `VaForms.project_id` covers all three of its branches), `get_site_pi_sites`,
  `get_project_pi_projects`.

Everything else reaches the rule through those two mechanisms:
`dm_scope_filter` / `_dm_scope_pairs`, `_expand_project_ids_to_active_pairs`
(given ids by the fixed resolvers — its docstring now says so),
`organization.py::_reachable_unit_ids`, `web_intake_service::_reachable_unit_ids`,
`is_viewer`, `is_data_manager`, `can_manage_project`.

`viewer_pii_service.should_redact_pii` takes the predicate too. It was first
left alone as "not an access check", and the security review showed why that
was wrong: a user with a plain collaborator grant on an open project and a
`collaborator_pii` grant on a closed one would keep seeing personal data on
the open project's screens through the dormant grant. Redaction is an access
decision about personal data, and it fails open when it disagrees with the
resolvers. The grant names its project differently per scope, so the check
resolves it per scope with subqueries correlated to the grant row; global
(admin) grants count unconditionally.

## Verification

`tests/test_closed_project_grants.py` — for each of a project-scoped
interviewer grant, a `project_site` coder grant, an `org_unit` grant, a
`data_manager` grant and a `project_pi` grant: access resolves while active,
is gone while closed, and returns on reopen. Plus an end-to-end control
through `GET /api/v1/data-management/filter-options` (a route with no
project-status pre-check), a check that the grant row survives closure
unchanged, and a positive control that a second, active project's grant for
the same user is unaffected.

## Docs

- `docs/policy/access-control-model.md` — "Closed Projects" (owns the rule)
- `docs/policy/organization-model.md` — cross-reference under "Unit-scoped grants"
- `docs/current-state/workflow-and-permissions.md` — "Closed projects resolve no grant"
