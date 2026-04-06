---
title: Test Harness Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-04-05
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

### Per-test isolation

`BaseTestCase` (in `tests/base.py`) uses PostgreSQL savepoint rollback:

1. `setUp()` calls `db.session.begin_nested()` (SAVEPOINT).
2. Test code may commit freely — commits only release the savepoint.
3. `tearDown()` calls `db.session.rollback()` — undoes all writes.

No manual DELETE or DROP is needed. This is the standard pattern for all
database-touching tests.

**Caveat:** Production code that calls `db.session.commit()` inside a savepoint
will release the savepoint, merging changes into the outer transaction. This
makes those changes visible to subsequent operations in the same test, but they
are still rolled back by `tearDown()`. Materialized view refreshes are an
exception — because `_refresh_one` calls `db.session.commit()`, MV tests manage
their own per-class DDL (create/drop MVs in setUpClass/tearDownClass).

### Base fixtures

`BaseTestCase._seed_base_fixtures()` creates shared reference data (admin,
project-PI, coder users; one project; one site). Seeding is idempotent: the
first class to call it inserts rows; subsequent classes find and reuse them.

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

### 5. Keep tests that don't need DB lightweight

Tests for pure functions, template rendering, or fully-mocked service calls
may use plain `unittest.TestCase` without inheriting `BaseTestCase`. Do not
pull in database infrastructure for tests that never touch it.

### 6. Use unique names for unique-constrained fields in tests

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
