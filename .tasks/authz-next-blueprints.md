Status: pending
Priority: high
Created: 2026-04-21

Goal:
Migrate the remaining business blueprints to the central TOML-backed authorization layer.

Context:
The first slice now covers `data_management`, `api_v1.data_management_api`,
`api_v1.cod_buckets_api`, and `api_v1.workflow`. The next slice now also covers
`coding` and `api_v1.coding_api`. `reviewing`, `va_form`, and attachment/media
routes still use legacy route auth and need policy-aligned cutover.

References:
- `docs/policy/authorization-policy.md`
- `docs/planning/access-control-grants-design.md`
- `docs/planning/authorization-route-action-audit.md`
- `app/authz/policy.toml`
- `app/routes/coding.py`
- `app/routes/api/coding.py`
- `app/routes/reviewing.py`
- `app/routes/va_form.py`

Expected Scope:
- extend the action catalog for reviewing, `va_form`, and attachment/media
- keep workflow/sync checks in predicates
- remove legacy route auth from each blueprint once migrated
- add focused route tests for each migrated blueprint
