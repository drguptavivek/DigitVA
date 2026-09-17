---
title: Test Harness Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-17
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

### 7. Use unique names for unique-constrained fields in tests

When creating test data inside savepoint-rollback tests, use unique names for
fields with unique constraints (e.g. `connection_name`). This prevents
conflicts when `commit()` inside the test releases the savepoint, making the
row visible to subsequent tests in the same class.

## Key files

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Session-scoped schema, connection cleanup |
| `tests/base.py` | `BaseTestCase` with savepoint rollback, shared fixtures |
| `config.py` (`TestConfig`) | Test database URL, pool settings, CSRF secrets |
