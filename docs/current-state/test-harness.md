---
title: Test Harness and Database Connection Management
doc_type: reference
status: current
owner: vgz
last_updated: 2026-03-09
---

# Test Harness and Database Connection Management

## Database

Tests run against a separate `minerva_test` PostgreSQL database (never the dev DB).
`TestConfig` sets `SQLALCHEMY_DATABASE_URI` to point at it.
Schema is created fresh per test class and dropped at the end — no persistent state between runs.

One-time setup (already done):
```
docker exec minerva_db psql -U minerva -c "CREATE DATABASE minerva_test;"
```

Run tests:
```
docker exec minerva_app python -m pytest tests/ -v
```

## BaseTestCase (`tests/base.py`)

All test classes inherit from `BaseTestCase` instead of `unittest.TestCase`.

### Class-level lifecycle

| Hook | What it does |
|------|-------------|
| `setUpClass` | Creates app + context, runs `db.create_all()`, seeds base fixtures |
| `tearDownClass` | `db.session.remove()`, `db.drop_all()`, pops context |

Base fixtures committed once per class:
- `BASE_PROJECT_ID = "BASE01"`, `BASE_SITE_ID = "BS01"`, one project-site mapping
- `base_admin_user` (global admin), `base_project_pi_user` (PI for BASE01), `base_coder_user` (coder for BS01)

### Per-test isolation (savepoint rollback)

```
setUp   → db.session.begin_nested()   # opens a PostgreSQL SAVEPOINT
tearDown → db.session.rollback()       # rolls back to before the savepoint
           db.session.expire_all()
```

Because the Flask test client shares the same scoped session as the test body, HTTP routes that call `db.session.commit()` only *release the savepoint* — they do not commit the outer transaction.  `tearDown` rolls back the outer transaction, leaving the DB clean for the next test.  No manual `DELETE` queries are needed.

**Key rule for subclass helpers**: use `db.session.flush()` (not `commit()`) when creating per-test data.  A `commit()` inside `setUp` releases the savepoint and makes data permanent, so `tearDown` cannot undo it.

**Unique identifiers**: helpers that create users must use unique email suffixes (e.g. `uuid.uuid4().hex[:8]`) to guard against cross-test leakage in the rare case a test makes multiple HTTP calls (each of which triggers its own inner `commit()`).

### Shared helpers

| Helper | Purpose |
|--------|---------|
| `_login(user_id)` | Injects a session without going through the login route |
| `_csrf_headers()` | Returns `{"X-CSRFToken": ...}` with a valid token for the current session |

## Subclass patterns

```python
class MyTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()          # always first
        # add class-level fixtures here; commit() is safe here (outside savepoints)

    def setUp(self):
        super().setUp()               # opens savepoint
        self.user = self._make_user("x@y.com", "Pw123")  # flush, not commit
```
