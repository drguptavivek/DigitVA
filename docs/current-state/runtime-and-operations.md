---
title: Runtime And Operations
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-04
---

# Runtime And Operations

## Summary

This document captures the current Python runtime, container setup, migrations, tests, logging, and adjacent operational features.

## Python Runtime

Current Python/runtime characteristics:

- Python `3.13` base image in [`Dockerfile`](../../Dockerfile)
- Flask application entrypoint via `FLASK_APP=run.py`
- primary dependency management via `uv` (see [`pyproject.toml`](../../pyproject.toml) and [`uv.lock`](../../uv.lock))

Key current libraries:

- Flask
- Flask-Login
- Flask-Migrate
- Flask-SQLAlchemy
- Flask-WTF
- SQLAlchemy
- Alembic
- psycopg2-binary
- pandas
- openpyxl
- pyodk
- pydub
- python-dotenv
- redis
- celery

Operational implication:

- this is a synchronous Flask application with ORM-backed DB access and file-based integration steps.
- **Session Timeout**: Sessions have a 30-minute inactivity timeout (`PERMANENT_SESSION_LIFETIME = 30 mins`). This is enforced via `session.permanent = True` on login.
- SmartVA form-run evidence is stored under the configured
  `APP_SMARTVA_RUNS` directory, which defaults to `/app/smartva_runs` in the
  container.

## Container And Docker Setup

### Application container

The app container is defined in [`Dockerfile`](../../Dockerfile).

Current behavior:

- starts from `astral/uv:python3.13-trixie`
- installs `postgresql-client` and `ffmpeg`
- installs Python dependencies via `uv sync`
- copies the repo into `/app`
- installs SmartVA-Analyze from `vendor/smartva-analyze` via `uv pip install --no-deps`
- marks `boot.sh` executable
- exposes port `5000`

Why the extra system packages exist:

- `postgresql-client` is needed for DB-related operational commands
- `ffmpeg` is needed for audio conversion via `pydub`

### Compose setup

The local/container runtime is defined in [`docker-compose.yml`](../../docker-compose.yml).

Current services:

- `minerva_app_service`
- `minerva_db_service`
- `minerva_redis_service`
- `minerva_celery_worker` (Celery worker)
- `minerva_celery_beat` (Celery beat)

Current behavior:

- local override binds the app to `127.0.0.1:5005`
- postgres is bound to host port `8450`
- redis is bound to host port `6379`
- source code is mounted into the container via `.:/app`
- postgres data is persisted in a named docker volume
- celery beat startup now waits for DB connectivity and the `celery_*` scheduler tables instead of relying on a fixed sleep
- celery worker startup uses `--concurrency=2`

Current health checks:

- app: `GET /health`
- db: `pg_isready -U minerva`

## Boot And Startup

Startup behavior is controlled by [`boot.sh`](../../boot.sh).

Current startup sequence:

1. retry `flask db upgrade` until DB is reachable
2. start Gunicorn with one worker on port `5000`

Current implication:

- schema migrations are applied automatically at container startup
- runtime is tightly coupled to the DB being available
- old-format live databases are expected to migrate forward via additive
  Alembic migrations rather than manual resets

## Database And Migrations

### Current migration tooling

The app uses:

- Flask-Migrate
- Alembic

Current migration files live under:

- [`migrations`](../../migrations)

Current migration posture:

- single-database configuration
- one checked-in initial migration file:
  - [`a395774fa312_new_initial_migration.py`](../../migrations/versions/a395774fa312_new_initial_migration.py)

### Current migration behavior

The app auto-runs:

- `flask db upgrade`

at startup via `boot.sh`.

This means the operational assumption is:

- the DB should be migrated to the latest schema whenever the app container boots

### Current caveat

The repo currently appears to rely heavily on:

- the initial migration
- shell-driven full initialization for master data and mappings

So schema migration and data initialization are related but distinct concerns in current operations.

## Tests

### Current state

The project has an automated test suite using `pytest`.

Key test files:
- `tests/base.py`: Base test case with DB isolation (savepoints).
- `tests/test_admin_api.py`: Tests for admin API security and access.
- `tests/test_auth_grants.py`: Tests for access control and role-based permissions.
- `tests/test_session.py`: Tests for session timeout and behavior.
- `tests/test_profile.py`: Tests for user profile updates (e.g., timezone).

Current implication:
- Test coverage is being actively built for critical areas like authentication, authorization, and session management.
- Tests run inside the application container using `uv run python -m pytest tests/`.
- `TestConfig` now uses filesystem-backed Flask sessions so the test harness
  does not fight schema lifecycle around `va_sessions`.

## Operational CLI

Current Flask CLI command groups include:

- `flask seed run`
- `flask form-types ...`
- `flask analytics ...`
- `flask odk-sync ...`
- `flask users ...`

Current `flask users ...` commands support:

- `list`
- `search`
- `list-grants`
- `create`
- `reset-password`
- `grant-admin`
- `revoke-admin`
- `set-status`

Operational implication:

- the app now has a shell-safe fallback for user bootstrap and admin recovery
- admin access created through the CLI still writes the same explicit global grant row used by runtime authorization

## Logging

### Current logging implementation

Logging is configured in:

- [`app/logging/va_logger.py`](../../app/logging/va_logger.py)

Logging is wired into the app in:

- [`app/__init__.py`](../../app/__init__.py)

Current log outputs:

- `logs/requests.log`
- `logs/errors.log`
- `logs/sql.log`

### Request and response logging

The app logs:

- user identity when available
- client IP
- method
- URL
- request payload with some sensitive fields masked
- trimmed response payload for text and JSON responses

Masked request fields currently include values such as:

- `password`
- `csrf_token`
- `new_password`
- `va_current_password`
- `va_new_password`
- `va_confirm_password`

### Error logging

Unhandled exceptions are logged to `errors.log` with stack traces.

### SQL logging

SQLAlchemy engine logging is enabled and routed to `logs/sql.log`.

Current filter behavior:

- only statements containing `INSERT`, `UPDATE`, or `DELETE` are logged by the custom [`SQLWriteFilter`](../../app/logging/va_queryfilter.py)

Current implication:

- write activity is easier to audit
- read/query performance analysis is not comprehensively captured in current SQL logs

## Frontend Runtime Helpers

### Shared toast notifications

The app now exposes a shared transient-notification helper:

- `window.showAppToast(message, type, options)`

Implementation:

- defined in [`app/static/js/base.js`](../../app/static/js/base.js)
- mounted with a shared bottom-right toast container in
  [`app/templates/va_frontpages/va_base.html`](../../app/templates/va_frontpages/va_base.html)

Current availability:

- all VA frontpages extending `va_base.html`
- the admin console, because
  [`app/templates/admin/admin_index.html`](../../app/templates/admin/admin_index.html)
  extends the same base template

Current behavior:

- toasts render in the bottom-right corner
- they auto-dismiss by default
- they can be closed manually
- flashed messages are surfaced through this helper on page load
- HTMX/JS workflows may call this helper directly for save success, validation
  warnings, and network errors

## Background Tasks

### Current scheduled tasks

The app seeds Celery beat schedules on worker startup in [`make_celery.py`](../../make_celery.py).

Current seeded periodic tasks:

- ODK sync every 6 hours
- stale coding allocation cleanup every 1 hour

Current ODK operational protection:

- DB-managed ODK connections are paced per connection before each outbound ODK
  request
- repeated retryable ODK connectivity/auth failures activate shared cooldown on
  the connection row
- app and worker processes use the same shared connection guard state

Current coding allocation cleanup behavior:

- implemented in
  [`app/services/coding_allocation_service.py`](../../app/services/coding_allocation_service.py)
- scheduled by [`app/tasks/sync_tasks.py`](../../app/tasks/sync_tasks.py)
- deactivates stale active coding allocations older than 1 hour
- preserves any saved `va_initial_assessments` rows
- writes an audit entry with action
  `va_allocation_released_due_to_timeout`

## Admin Operations

### Workflow activity panel

The admin console now includes an admin-only `Activity` panel.

Current behavior:

- reads from `va_submissions_auditlog`
- supports server-side filters for `SID`, `project`, `site`, `actor`, and row limit
- shows workflow-oriented stage labels for key coder milestones

The panel is intended for operational tracing of coding progress rather than raw
database inspection.

### ODK operator visibility

The admin console now exposes ODK connection health in multiple places:

- ODK Connections panel: per-connection cooldown and recent failure state
- Project Forms panel: selected project's connection state in the connection bar
- Sync Dashboard: active connection alerts in the status card

This visibility is driven from shared DB-backed guard state on
`mas_odk_connections`, not from extra live ODK checks.

## Emailing

### Current state

I did not find any actual outbound email implementation in the repository.

No evidence found for:

- Flask-Mail
- SMTP client setup
- SES / SendGrid integration
- mail sending services

What does exist:

- `email_validator` dependency in [`requirements.txt`](../../requirements.txt)
- user model fields like `email` and `email_verified`

Current implication:

- email addresses are stored and validated
- there is no implemented email delivery feature in the current codebase
- onboarding/password reset behavior is not driven by a real email delivery subsystem in this repo

## Infra Assumptions

Current infra assumptions visible in the repo:

- one Flask app service
- one PostgreSQL database
- local disk used for synced CSV files and attachments
- local disk used for logs
- local resource files used for mappings, SmartVA assets, and pyODK config

Current ODK configuration model:

- DB-managed ODK connections are the primary runtime path
- legacy `odk_config.toml` remains only as a backward-compatibility fallback
  for unmapped projects

This is a simple deployment shape, not a cloud-native split-service architecture.

## Operational Gaps Worth Noting

- no implemented email delivery subsystem
- no UI for infrastructure/admin setup
- logs are file-based, not centralized
- attachment and sync data are stored on local/shared disk paths
- live ODK behavior still depends on one shared Central instance being healthy,
  though the app now uses per-connection pacing and cooldown to reduce burst
  pressure

These constraints matter for any future move toward multi-project and multi-server onboarding.
