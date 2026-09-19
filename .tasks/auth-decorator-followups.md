---
title: Auth decorator follow-ups
doc_type: task
status: open
owner: engineering
last_updated: 2026-09-19
---

# Auth decorator follow-ups

Raised by the session that made `role_required` reject unknown role names
(`d1b75ee`). That change guarantees a route's role names are real. None of
the below is covered by it.

## 1. Nothing guarantees a route has a decorator at all

An unguarded route is strictly worse than a mistyped one: a mistyped name now
fails at import, while a missing decorator **fails open** and serves everyone.
`docs/policy/access-control-model.md` records three found by audit, one of them
a field-mapping panel that was simply unguarded.

Close the class permanently with a test that walks `app.url_map`, resolves each
endpoint to its view function, and asserts it is wrapped -- or is on an explicit
allowlist (health, static, login).

Use `url_map` at runtime, **not** an `ast` sweep: only the runtime map sees
blueprints registered dynamically.

## 2. `is_api` is a hardcoded prefix tuple

`role_required` decides JSON-vs-HTML from a literal tuple: `/api/`,
`/admin/api/`, `/data-management/api/`, `/intake/api/`. A new API blueprint at
a fifth prefix gets an HTML redirect instead of a JSON 401, so `base.js` never
shows the session-expired modal. The failure is silent and surfaces as "my tab
stopped refreshing".

Either derive it from the blueprint, or assert the tuple against the registered
blueprints in a test.

## 3. `project_pi` is the only predicate that queries

`"project_pi": lambda u: bool(u.get_project_pi_projects())` runs a query;
every other predicate reads a cached flag. On routes gated
`("admin", "project_pi")` admins short-circuit before it because `any()`
evaluates left to right -- but that ordering is incidental. Reversing the
argument order at any call site would make the query unconditional.

## Known seams in the tests that landed with `d1b75ee`

- The three positive controls use a `_StubUser`, not a real `VaUsers`. They
  verify the decorator's gating logic, not that `is_coder()`/`is_admin()` mean
  what the grants system thinks. Covered elsewhere, but the seam is real.
- `assert "view" not in locals()` in the decoration-time test is nearly
  tautological. The load-bearing assertions there are
  `not flask.has_request_context()` and `not body_ran`.
- `docs/policy/auth-decorator-rbac.md` sections 6-8 still describe the
  completed 2026-04-05 blueprint migration as current-state tables. Left
  deliberately: rewriting a historical record was outside that change.
