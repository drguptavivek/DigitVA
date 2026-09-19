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

## 1. Nothing guarantees a route has a decorator at all — DONE (2026-09-19)

**Done:** `tests/test_route_auth_coverage.py` walks `app.url_map` and fails on any
endpoint carrying neither `role_required`'s new `__digitva_roles__` marker nor
Flask-Login's `login_required`, with one reasoned allowlist that cannot drift.

**Decision (2026-09-19):** the pending list is gone. `help.index`, `help.page`,
`help.docs_index`, `help.doc_page` and `va_main.who_va_document` are settled as
`PUBLIC_BY_DESIGN`, and so is `va_main.va_index`: `/` is the public home page and
the login page is a separate route (a `login_required` on `/` was reverted the
same day). Every route
is guarded or public by design -- see docs/policy/auth-decorator-rbac.md
section 3 and tests/routes/test_public_route_access.py.

An unguarded route is strictly worse than a mistyped one: a mistyped name now
fails at import, while a missing decorator **fails open** and serves everyone.
`docs/policy/access-control-model.md` records three found by audit, one of them
a field-mapping panel that was simply unguarded.

Close the class permanently with a test that walks `app.url_map`, resolves each
endpoint to its view function, and asserts it is wrapped -- or is on an explicit
allowlist (health, static, login).

Use `url_map` at runtime, **not** an `ast` sweep: only the runtime map sees
blueprints registered dynamically.

## 2. `is_api` is a hardcoded prefix tuple — DONE (2026-09-19)

**Done:** extracted to `API_PATH_PREFIXES` in `role_required.py`; asserted against
the registered rules in `tests/test_route_auth_coverage.py`. Not derived from the
blueprints — an unlisted prefix is now a test failure, not a silent HTML redirect.

`role_required` decides JSON-vs-HTML from a literal tuple: `/api/`,
`/admin/api/`, `/data-management/api/`, `/intake/api/`. A new API blueprint at
a fifth prefix gets an HTML redirect instead of a JSON 401, so `base.js` never
shows the session-expired modal. The failure is silent and surfaces as "my tab
stopped refreshing".

Either derive it from the blueprint, or assert the tuple against the registered
blueprints in a test.

## 3. `project_pi` is the only predicate that queries — DONE (2026-09-19)

**Corrected premise.** "Every other predicate reads a cached flag" was wrong.
`VaUsers.is_admin()` is itself a query -- an EXISTS over the global-scope admin
grant -- and the role predicates generally resolve grants rather than read
flags. Nothing is cached per request. So the Layer-3 `any()` runs over booleans
that each cost a round trip, and the decision is already order-independent:
reversing `role_required("admin", "project_pi")` changes which query runs
first, not whether one runs.

**Done:** what was actually wrong was the cost class. The gate asked *which*
projects in order to answer *any* project. `VaUsers.is_project_pi()` asks the
second question directly -- an `sa.exists()` over the same four grant
conditions plus `active_project_condition`, so a closed project still yields
False -- and `_ROLE_METHODS["project_pi"]` now calls it.
`get_project_pi_projects()` is unchanged and still answers scope.

**Proved by** `tests/test_role_required_project_pi_predicate.py`: the semantics
including the closed-project flip, both argument orders returning identical
statuses (200/200, 200/200, 403/403) for an admin, a project PI and a plain
user, and a `before_cursor_execute` count showing one statement whose SELECT
list is a boolean -- with `get_project_pi_projects()` as the positive control
in the same test, since both statements contain EXISTS and only the SELECT list
discriminates.

Per-request caching of the predicates was considered and left out of scope: it
is a change to every role gate, not to this one.

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
