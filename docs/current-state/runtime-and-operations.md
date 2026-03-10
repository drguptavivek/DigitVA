---
title: Runtime And Operations
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-03-10
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

## Container And Docker Setup

### Application container

The app container is defined in [`Dockerfile`](../../Dockerfile).

Current behavior:

- starts from `astral/uv:python3.13-trixie`
- installs `postgresql-client` and `ffmpeg`
- installs Python dependencies via `uv sync`
- copies the repo into `/app`
- marks `resource/smartva` and `boot.sh` executable
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
- `minerva_worker_service` (Celery worker)
- `minerva_beat_service` (Celery beat)

Current behavior:

- app is bound to host port `8050`
- postgres is bound to host port `8450`
- redis is bound to host port `6379`
- source code is mounted into the container via `.:/app`
- postgres data is persisted in a named docker volume

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

This is a simple deployment shape, not a cloud-native split-service architecture.

## Operational Gaps Worth Noting

- no implemented email delivery subsystem
- no UI for infrastructure/admin setup
- ODK configuration is file-based and global
- logs are file-based, not centralized
- attachment and sync data are stored on local/shared disk paths

These constraints matter for any future move toward multi-project and multi-server onboarding.
