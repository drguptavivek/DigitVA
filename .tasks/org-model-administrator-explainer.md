# Administrator explainer for the organization and permission model

- Status: pending (blocked on phases 3–4)
- Priority: medium
- Created: 2026-09-18

## Goal

A standalone explainer for PIs, programme officers and administrators —
non-engineers who need to understand who can see and code what — covering the
organization tree, roles, scopes, grants and cadres, with screenshots of the
Organization and Access Grants panels.

## Context

`docs/policy/organization-model.md` now opens with an "In plain terms"
orientation section (added 2026-09-18) that carries the concepts in
non-technical language. That covers the immediate need and lives next to the
rules, so it stays in step with them.

A separate audience-facing document is deliberately deferred: until submission
routing (phase 3) and coding-scope enforcement (phase 4) land, a unit-scoped
grant is recorded but changes nothing a coder sees. An explainer that has to
say "this is stored but does not do anything yet" would mislead more than it
helps, and its screenshots would be re-shot afterwards anyway.

## Blocked on

Phases 3 and 4 of `.tasks/health-system-organization-model.md`.

## References

- `docs/policy/organization-model.md` (orientation section + rules)
- `docs/policy/access-control-model.md` (roles, scopes, grant storage)
- `docs/current-state/admin-and-setup.md` (Organization panel, Access Grants panel)
- `.tasks/health-system-organization-model.md` (phase order)

## Expected Scope

- one document under `docs/` with YAML front matter, aimed at administrators
- worked examples: an SMO overseeing a CHC subtree, an MO coding at one PHC,
  a CHO who fills forms but cannot code
- panel screenshots taken once enforcement is live
- state explicitly what a person can and cannot reach, rather than describing
  tables and columns
