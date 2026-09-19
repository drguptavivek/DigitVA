# Closed projects do not revoke project-scoped grants

- **Status**: open
- **Priority**: medium
- **Created**: 2026-09-19

## Goal

Decide what a closed project (`va_project_master.project_status != active`)
means for every grant scope, and apply that decision consistently in both
mechanisms that currently ignore it.

## Context

A grant with `scope_type = project` on a closed project still resolves to
access, in two independent places that do not call each other:

1. `app/services/org_grant_service.py::project_wide_grant_exists` — the
   site-scoped branch joins `VaProjectSites` and requires
   `project_site_status == active`; the project-scoped branch checks only
   `grant_status` and never checks the project's own status.

2. `app/models/va_users.py:430::_get_granted_project_ids` filters
   `grant_status`, `scope_type` and `role`, but not project status.
   `app/services/submission_analytics_mv.py:937::_expand_project_ids_to_active_pairs`
   then expands those ids filtering only `project_site_status`, so a
   `data_manager` grant on a closed project resolves to active
   `(project_id, site_id)` pairs.

Both behaviours predate 2026-09-19. The shared assumption is that a closed
project's grants are already revoked; nothing enforces it.

Impact today is bounded only by callers — the organization API 404s on a
non-active project before reaching (1). That is a property of that caller,
not of either mechanism, and any new caller inherits the gap.

## Expected Scope

- Decide the rule for `project`, `project_site` and `org_unit` scopes.
- Apply it in **both** mechanisms. Fixing one alone leaves two mechanisms
  disagreeing, which is worse than one honest gap.
- Tests: a project-scoped grant and a `data_manager` grant, each on a closed
  project.

## References

- `app/services/org_grant_service.py` — `project_wide_grant_exists` docstring
  carries the full semantics of that function.
- `app/models/va_users.py:422-440`
- `app/services/submission_analytics_mv.py:937`
- `docs/policy/organization-model.md`

Found while collapsing the organization API's copy of the project-wide check
into `org_grant_service`. Second instance found by the Organization model
session and verified independently against HEAD.
