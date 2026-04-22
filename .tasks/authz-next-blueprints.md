Status: pending
Priority: high
Created: 2026-04-21

Goal:
Migrate the remaining business blueprints to the central TOML-backed authorization layer.

Context:
The first slice now covers `data_management`, `api_v1.data_management_api`,
`api_v1.cod_buckets_api`, and `api_v1.workflow`. The next slice now also covers
`coding`, `api_v1.coding_api`, `reviewing`, `api_v1.reviewing_api`, `va_form`,
`api_v1.nqa_api`, `api_v1.so_api`, `api_v1.analytics`, and the
`api_v1.dm_kpi_*` read/refresh APIs, and `api_v1.icd10_api`. The main remaining
authz surface is now self-scoped profile APIs if we choose to centralize them,
plus any later non-API route families still on legacy auth.

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
- extend the action catalog for remaining straggler APIs
- keep workflow/sync checks in predicates
- remove legacy route auth from each blueprint once migrated
- add focused route tests for each migrated blueprint
