---
title: Test Harness Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-19
---

# Test Harness Policy

## Architecture

The test suite uses pytest with a session-scoped PostgreSQL schema against the
`minerva_test` database. Tests run inside Docker:
`docker compose exec minerva_app_service uv run pytest tests/ -v`

### Schema lifecycle

- **Session start** (`conftest.pytest_sessionstart`): terminate stale connections,
  create schema via `db.create_all()`.
- **Session end** (`conftest.pytest_sessionfinish`): drop schema, dispose engine.
- **No per-class or per-test DDL.** The schema is created once and shared.

### Isolation: class transaction plus per-test savepoint

Nothing a test class writes ever reaches the database. `BaseTestCase`
(in `tests/base.py`) joins the scoped session to an external transaction:

1. `setUpClass()` opens one connection, begins a transaction on it, and binds
   `db.session` to that connection with `join_transaction_mode="create_savepoint"`.
   Base fixtures and class fixtures are seeded inside this transaction.
2. `setUp()` opens a SAVEPOINT on that connection, one level inside the class
   transaction.
3. `tearDown()` rolls back to the per-test savepoint. Class fixtures survive for
   the rest of the class.
4. `tearDownClass()` rolls back the class transaction and closes the connection,
   so no class can leak rows into another.

Because the session joins through a savepoint of its own, `db.session.commit()`
inside a test — from test code or from route code — only releases the session's
savepoint. Committing more than once in a test is safe; DDL such as materialized
view creation is rolled back with everything else, so a test that queries an MV
must build it itself.

Flask-SQLAlchemy's `Session.get_bind()` ignores an explicitly bound connection,
so `conftest.pytest_sessionstart` installs `ExternalTransactionSession`
(`tests/base.py`) as the session class before any session is used.

**Exception — code that opens its own engine connection.** Code that goes to
`db.engine` directly (the ODK connection guard keeps its state outside the
request transaction by design) runs on another connection and cannot see rows
held in the class transaction. Such a class sets `isolate_in_transaction = False`,
writes for real, and MUST delete what it created in its own `tearDownClass`.

**`_login()` and Flask-Login's cache.** The app context lives for the whole
pytest session, so `g._login_user` survives between requests. `_login()` clears
it before injecting the new session; without that a second `_login()` inside one
test is a silent no-op and any privilege-boundary assertion after it passes
vacuously.

### Base fixtures

`BaseTestCase._seed_base_fixtures()` creates shared reference data (admin,
project-PI, coder users; one project; one site) inside each class's transaction,
so every class gets a fresh copy. Class-level fixtures that reuse shared ids
(the BASE research project and site, form types, languages) must still be
get-or-create — see Rule 5 — because helper code and some tests seed the same
rows.

## Rules

### 1. Use BaseTestCase, never plain unittest.TestCase for DB tests

Any test that touches the database must inherit `BaseTestCase`. Never call
`db.drop_all()`, `db.create_all()`, or `db.session.remove()` in test
setUp/tearDown.

### 2. Never create a second Flask app inside tests

`conftest.pytest_sessionstart` creates one session-scoped app and pushes its
context for the entire session. Do **not** call `create_app(TestConfig)` inside
test methods, setUp, or setUpClass. Use `from app import db` directly — the
session-scoped context is already active.

**Exceptions.** Four places need an app the session app cannot be: the
migration guards (`tests/migrations/test_schema_drift.py`,
`test_attachment_state_backfill.py`) run `flask db upgrade` against a throwaway
database, and the object-store tests (`tests/services/test_attachment_store.py`
and everything importing its `make_s3_app`) need `ATTACHMENT_STORE=s3` without
imposing it on the session app. All four build the app through
`tests.base.create_app_without_celery_takeover()`, use a nested app context, and
never touch the shared session schema. No other test may follow them — and any
that does must go through that helper (see rule 7).

### 3. Tests that mock db.session do not need create_app

If a test mocks `db.session` or patches `app.db`, it can use those mocks
directly under the session-scoped context. No local app instance is needed.

### 4. Use unique IDs for class-scoped fixtures

Subclasses that add their own fixtures in `setUpClass` must use unique IDs
(e.g. `PROJECT_ID = "MYTEST01"`) to avoid conflicts with base fixtures and
other test classes in the same session.

### 5. Class-level fixtures that reuse shared IDs must be get-or-create

`setUpClass` runs outside the per-test savepoint and its writes are committed,
so they live for the whole session. Any class-level insert that reuses an ID
another class may also use — `BASE_PROJECT_ID`/`BASE_SITE_ID`, a derived
`FORM_ID`, reference rows such as `mas_languages` or `mas_form_types`, or a
fixture shared with a subclass — must be get-or-create (`db.session.get` or a
scalar select), never an unconditional insert. An unconditional insert raises
`UniqueViolation` the moment another class has already committed the row, and
the poisoned scoped session then breaks every later class.

For the legacy `va_research_projects` / `va_sites` rows use the shared helper
`BaseTestCase._ensure_base_research_project_and_site()`. It is opt-in: call it
from `setUpClass` when the class needs those rows; `_seed_base_fixtures()` does
not create them.

Two classes must not share a site ID across different projects: the analytics
MVs join `va_project_sites` on `site_id` alone, so a second active project-site
row for the same site duplicates every submission row in the MV.

### 6. Keep tests that don't need DB lightweight

Tests for pure functions, template rendering, or fully-mocked service calls
may use plain `unittest.TestCase` without inheriting `BaseTestCase`. Do not
pull in database infrastructure for tests that never touch it.

### 7. A test that changes global state must restore it

The app, its `extensions` dict and the Celery process globals are **session
scoped**: whatever a test leaves in them is what every later module sees. Two
real leaks came from this and both are fixed at the source:

- Stubbing an extension (`app.extensions["celery"] = object()`) must save the
  previous value and restore it from `addCleanup`/`tearDown`, including the case
  where the key was absent.
- Building a second app must not let it take over Celery. `celery_init_app`
  calls `set_default()`, and `Celery.__init__` also makes itself *current*, so a
  throwaway app silently becomes the app every `shared_task` resolves against —
  and `FlaskTask.__call__` then pushes that app's context and config. Use
  `tests.base.create_app_without_celery_takeover()` (see rule 2 for when a
  second app is allowed at all), which restores both globals.

The same applies to `app.config` overrides, `ATTACHMENT_STORE` in particular:
flip it through a helper that restores the old value and drops the cached
`app.extensions["attachment_store"]` — `DbBackupBase._pin_local_store` is the
pattern.

### 8. Use unique names for unique-constrained fields in tests

When creating test data inside savepoint-rollback tests, use unique names for
fields with unique constraints (e.g. `connection_name`). This prevents
conflicts when `commit()` inside the test releases the savepoint, making the
row visible to subsequent tests in the same class.

## Checks that cannot fail for what they appear to test

Four separate times in one week a check passed while proving nothing. They
did not share a bug — each one was honest about its own logic. What they
shared is that the **subject of the assertion was absent**, so the
assertion passed against nothing:

- a migration replay that replayed the in-tree revisions rather than the
  committed chain, so a broken `down_revision` on origin could not surface
- two test classes whose `setUpClass` errored on a missing FK row (see the
  dual-table trap below); an errored class is not a failing class, and the
  suite stayed green
- a per-unit coding-gate test whose call short-circuited on a null
  `org_unit_id` and never reached the gate logic at all — it also passed the
  wrong form id, so the query it did run saw zero rows
- a redaction test written against a fixture (`DataManagerDashboardTests`)
  whose `coder_name`, `reviewer_name` and allocation-name columns are all
  empty, so "the name is gone after redaction" was true before redaction too

### Rule: assert the subject is present before asserting it is absent

Any test of the form *"X is not there after we do Y"* must first assert that
**X is there before Y**. Without that line the test cannot distinguish the
behaviour it is named for from a fixture that never contained X.

This applies most sharply to redaction, filtering, scoping and exclusion
tests, which are exactly the tests that guard access to personal data — and
exactly the ones whose silent passing is most expensive.

Two supporting habits:

- **A positive control in the same test.** Where the behaviour is
  differential ("this project is affected, that one is not"), assert the
  affected case in the same test. If the machinery is dead, the control
  fails and tells you so; the negative case alone cannot.
- **Treat an errored `setUpClass` as the whole class unverified.** pytest
  reports it distinctly from a failure and it is easy to skim past. A class
  that errored in setup has tested nothing, regardless of what the summary
  line says.

### Rule: patch the module object, not a dotted path through a package

`monkeypatch.setattr("pkg.module.attr", value)` resolves `pkg.module` by
attribute traversal, not by import. If the package's `__init__.py` re-exports a
name from the submodule, that name in the package namespace is the **function**,
and the traversal stops there: the patch hangs a stray attribute off a function
object and the real module global is never touched.

`app/decorators/__init__.py` does exactly this with `role_required`, so
`monkeypatch.setattr("app.decorators.role_required.current_user", stub)` is a
silent no-op. `raising=False` suppresses the one complaint that would have
surfaced it.

Patch the module object instead:

```python
_decorator_module = importlib.import_module("app.decorators.role_required")
monkeypatch.setattr(_decorator_module, "current_user", stub)
```

and do not pass `raising=False` to silence a target you have not verified --
that flag is for attributes that legitimately may not exist, not for making a
bad path quiet.

This one is worth calling out separately because the vacuity is structural
rather than fixture-shaped: nothing about the test data is wrong, and the test
reads correctly. Whether it fails loudly depends only on which branch the
un-patched object happens to take. The case that found it was patching a
`current_user` stub; it failed only because an anonymous user 401s on the deny
path. The same mistake on an admit-path test would have passed while asserting
against a decorator it never touched.

### Rule: a missing fixture can make an authorization test vacuous too

Three route tests for the viewer roles returned 500 because the analytics
materialized views did not exist -- conftest drops them and never rebuilds
them. Authorization had passed; only the MV query failed. Had those tests
asserted `!= 403` rather than `== 200`, they would have gone green while
proving nothing about either the route or the view.

Assert the status you actually expect. `not forbidden` is not a proof of
`reachable`, and on a route whose gate you are changing, the difference is
the whole test.

## Seeding a project: the dual-table trap

This repository keeps **two** project tables and **two** site tables, and
different foreign keys point at different ones:

- `va_forms.project_id` -> `va_research_projects`
- `va_sites.project_id` -> `va_research_projects`
- `va_project_sites.project_id` -> `va_project_master`

So a fixture that seeds only `VaProjectMaster` — the newer org-model master
table, and the one most people reach for — fails at the first `va_forms` or
`va_sites` insert with

    insert on va_forms violates fk_va_forms_project_id_va_research_projects

**Seed both project rows, and both site rows** (`VaSiteMaster` and `VaSites`),
matching the pattern in `tests/services/test_runtime_form_sync_service.py`.

This is not a quirk of one test. On 2026-09-18 it broke two separate new test
classes within an hour of each other, and in both cases the failure was in
`setUpClass`, which means **every test in the class errored without running a
single assertion**. Both times the suite reported errors rather than
failures, and both times the feature under test was entirely unverified while
looking merely "a bit red".

When a `setUpClass` errors, treat the whole class as unverified rather than
as a flaky fixture to retry.

## Key files

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Session-scoped schema, connection cleanup |
| `tests/base.py` | `BaseTestCase` with savepoint rollback, shared fixtures |
| `config.py` (`TestConfig`) | Test database URL, pool settings, CSRF secrets |
