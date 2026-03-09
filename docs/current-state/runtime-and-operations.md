# Runtime And Operations

## Summary

This document captures the current Python runtime, container setup, migrations, tests, logging, and adjacent operational features.

## Python Runtime

Current Python/runtime characteristics:

- Python `3.11` base image in [`Dockerfile`](C:\workspace\DigitVA\Dockerfile)
- Flask application entrypoint via `FLASK_APP=run.py`
- primary dependency list in [`requirements.txt`](C:\workspace\DigitVA\requirements.txt)

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

Operational implication:

- this is a conventional synchronous Flask application with ORM-backed DB access and file-based integration steps

## Container And Docker Setup

### Application container

The app container is defined in [`Dockerfile`](C:\workspace\DigitVA\Dockerfile).

Current behavior:

- starts from `python:3.11-slim`
- installs `postgresql-client` and `ffmpeg`
- installs Python dependencies plus `gunicorn`
- copies the repo into `/app`
- marks `resource/smartva` and `boot.sh` executable
- exposes port `5000`

Why the extra system packages exist:

- `postgresql-client` is needed for DB-related operational commands
- `ffmpeg` is needed for audio conversion via `pydub`

### Compose setup

The local/container runtime is defined in [`docker-compose.yml`](C:\workspace\DigitVA\docker-compose.yml).

Current services:

- `minerva_app_service`
- `minerva_db_service`

Current behavior:

- app is bound to host port `8050`
- postgres is bound to host port `8450`
- source code is mounted into the container via `.:/app`
- postgres data is persisted in a named docker volume

Current health checks:

- app: `GET /health`
- db: `pg_isready -U minerva`

## Boot And Startup

Startup behavior is controlled by [`boot.sh`](C:\workspace\DigitVA\boot.sh).

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

- [`migrations`](C:\workspace\DigitVA\migrations)

Current migration posture:

- single-database configuration
- one checked-in initial migration file:
  - [`a395774fa312_new_initial_migration.py`](C:\workspace\DigitVA\migrations\versions\a395774fa312_new_initial_migration.py)

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

I did not find an actual test suite in the repository.

No evidence found for:

- `tests/` directory
- `pytest` config or test files
- `unittest` suites
- CI-oriented test runners in the repo itself

Current implication:

- the repository appears to have no committed automated test coverage
- behavior validation is likely manual and workflow-driven

### Practical consequence

Any refactor of:

- schema
- sync
- permissions
- workflow transitions

will currently rely on manual verification unless a test harness is introduced.

## Logging

### Current logging implementation

Logging is configured in:

- [`app/logging/va_logger.py`](C:\workspace\DigitVA\app\logging\va_logger.py)

Logging is wired into the app in:

- [`app/__init__.py`](C:\workspace\DigitVA\app\__init__.py)

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

- only statements containing `INSERT`, `UPDATE`, or `DELETE` are logged by the custom [`SQLWriteFilter`](C:\workspace\DigitVA\app\logging\va_queryfilter.py)

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

- `email_validator` dependency in [`requirements.txt`](C:\workspace\DigitVA\requirements.txt)
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

- no committed automated test suite
- no implemented email delivery subsystem
- no UI for infrastructure/admin setup
- ODK configuration is file-based and global
- logs are file-based, not centralized
- attachment and sync data are stored on local/shared disk paths

These constraints matter for any future move toward multi-project and multi-server onboarding.
