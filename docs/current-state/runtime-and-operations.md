---
title: Runtime And Operations
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-17
---

# Runtime And Operations

## Summary

This document captures the current Python runtime, container setup, migrations, tests, logging, and adjacent operational features.

## Python Runtime

Current Python/runtime characteristics:

- Python `3.13` base image (`python:3.13-slim`) in [`Dockerfile`](../../Dockerfile)
- Flask application entrypoint via `FLASK_APP=run.py`
- primary dependency management via `uv` (see [`pyproject.toml`](../../pyproject.toml) and [`uv.lock`](../../uv.lock))
- SmartVA installed as a uv path dependency from `vendor/smartva-analyze` (git submodule)

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
- python-dotenv
- redis
- celery
- smartva (via path dependency, GUI deps excluded)

Operational implication:

- this is a synchronous Flask application with ORM-backed DB access and file-based integration steps.
- **Session Timeout**: Sessions have a 30-minute inactivity timeout (`PERMANENT_SESSION_LIFETIME = 30 mins`). This is enforced via `session.permanent = True` on login.
- password creation and reset flows now reject passwords found in the Have I Been Pwned breach corpus using the shared password policy helper
- SmartVA form-run evidence is written under the configured `APP_SMARTVA_RUNS`
  directory, which defaults to `/app/smartva_runs` in the container, and is
  then archived to the object store and removed from the VM — see
  **SmartVA Run Archive** below.

## Container And Docker Setup

### Application container

The app container is defined in [`Dockerfile`](../../Dockerfile).

Current behavior:

- multi-stage build:
  - **Builder stage**: `python:3.13-slim` + `uv` binary, runs `uv sync --frozen --no-dev`
  - **Runtime stage**: `python:3.13-slim`, copies `uv` and `.venv` from the build stages
- installs `postgresql-client`, `sox`, and `libsox-fmt-all` for audio conversion
- SmartVA installed as a uv path dependency (`vendor/smartva-analyze`)
- marks `boot.sh` executable
- exposes port `5000`
- `PATH` includes `/app/.venv/bin` so all Python entrypoints (`flask`, `celery`, `gunicorn`) work without `uv run`

Why the extra system packages exist:

- `postgresql-client` is needed for `pg_dump`/`psql` in DB backup and Celery beat startup
- `sox` and `libsox-fmt-all` handle AMR→M4A/AAC audio conversion (replaces `ffmpeg`)

### Compose setup

The local/container runtime is defined in [`docker-compose.yml`](../../docker-compose.yml).

Current services:

- `minerva_app_service`
- `minerva_db_service`
- `minerva_redis_service`
- `minerva_celery_worker` (Celery worker)
- `minerva_celery_beat` (Celery beat)

Current behavior:

- local override (`docker-compose.override.yml`) runs Flask dev server on `0.0.0.0:5000`, mapped to host port `8051`
- the dev override now activates a dedicated development config via `FLASK_ENV=development`, which disables `Secure` session/remember cookies and strict HTTPS-only CSRF checks so login works on plain `http://localhost:8051`
- redis is bound to host port `6379`
- source code is mounted into the container via `.:/app`
- a named `minerva_venv` volume preserves the image's `/app/.venv` from the host mount and is shared by the app, Celery worker, and Celery beat services
- the app, Celery worker, and Celery beat services now build for the host's native Docker architecture by default; when changing host architecture or switching between emulated/native builds, recreate the shared `minerva_venv` volume so compiled wheels are rebuilt consistently
- postgres data is persisted in a named docker volume
- the dev override uses the image-bundled `uv` binary to run `uv sync --frozen` at container start, rather than installing `uv` with `pip`
- both image build and dev startup run [`scripts/sync_smartva_package_data.py`](../../scripts/sync_smartva_package_data.py) immediately after `uv sync` so SmartVA CSV/JSON/resource assets from the vendored source are copied into the installed package inside `/app/.venv`
- [`scripts/manual-db-restore.sh`](../../scripts/manual-db-restore.sh) is now operator-guided: it tells the user to stop app-side containers first, verifies the target database has no active sessions before dropping it, restores the dump, performs a post-restore sequence audit that prints exact `setval(...)` fix commands if any sequence lags behind table data, warns that restored ODK credentials require the same `ODK_CREDENTIAL_PEPPER` as the source instance, then prints the exact restart and migration commands to run next
- the admin Sync dashboard's attachment counts now distinguish expected attachments from files actually present on local disk; the “Attachments” column is backed by a filesystem check under `APP_DATA/<form_id>/media/<storage_name>` with `local_path` fallback, and the repair coverage table now also shows current-vs-legacy attachment row counts so `storage_name IS NULL` rows are visible separately from current storage rows
- the admin Sync dashboard now resolves forms from active `map_project_site_odk` site mappings, matching the main sync engine, so stale legacy `va_forms` rows no longer appear just because they are still marked active
- single-form backfill/repair now also checks for missing local attachment files on disk, excludes shared `audit.csv` artifacts from those file counts, treats legacy attachment rows (`storage_name IS NULL`) as repair gaps, and migrates those rows onto opaque storage names during the same attachment repair run
- ODK payload/comment fetches in the repair path now use explicit bounded request timeouts (`ODK_CONNECT_TIMEOUT_SECONDS`, `ODK_READ_TIMEOUT_SECONDS`), and repair batch sizes for enrichment/attachment stages are currently reduced to `5` submissions per batch to keep per-batch ODK call windows shorter
- Celery worker and beat wait for the app container to become healthy before starting so dependency refreshes propagate through the shared virtualenv before task processes launch
- celery beat startup waits for DB connectivity and the `celery_*` scheduler tables instead of relying on a fixed sleep
- the live migration chain now includes a forward-only additive migration that ensures the required `celery_*` scheduler tables exist on fresh databases
- celery worker startup uses `--concurrency=1`
- all services run Python entrypoints directly (`flask`, `celery`, `gunicorn`) — no `uv run` wrapper needed

Current health checks:

- app: Python `urllib.request.urlopen('/health')` (no `curl`/`wget` in slim image)
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
- `TestConfig` disables external password breach lookups so test runs stay deterministic; the breach check itself is covered by focused unit tests with mocked HTTP responses.

## Operational CLI

Full command reference: [`docs/current-state/cli-reference.md`](cli-reference.md)

Operational implication:

- the app now has a shell-safe fallback for user bootstrap and admin recovery
- admin access created through the CLI still writes the same explicit global grant row used by runtime authorization
- targeted operational repairs are also exposed through Flask CLI commands, including
  historical Step 1 reactivation after the old final-COD deactivation behavior

## Attachment Delivery

### Two copies, and which one is read

DigitVA keeps its **own permanent copy** of every attachment — originals and the
MP3 derivatives it makes — and that store is the read path for
`/vaform/attachment/<storage_name>`. ODK Central keeps its own copy and remains
the source of truth for existence and content, but it is not consulted on every
request. The store is either local files under `APP_DATA/<form_id>/media/` or a
private DigitVA-owned S3 bucket, selected once by `ATTACHMENT_STORE` and
implemented in `app/services/attachment_store.py`. Only delivery knows the
difference, and only because it must choose between sending a file and issuing
a redirect.

Delivery order:

1. the store has the object -> serve it. Local store: `send_file`, `Range`
   supported, `private, no-store`. S3 store: `302` to a presigned GET, with
   `private, no-store` on the redirect itself and `Range` answered by S3;
2. store miss, and the submission is retired, the row is an MP3 derivative, or
   the project flag is off -> `404`, exactly as before;
3. store miss otherwise -> fetch the original from the project's own ODK Central
   connection, stream it to the browser, and write it into the store on the way
   past. Local store: temp file plus atomic rename. S3 store: the body is
   spooled to a bounded temp file — one 64 KiB buffer in memory at a time — and
   then uploaded with a single atomic `put_object`. Either way a failed fetch
   leaves no object and no temp file;
4. a failed fetch is `404` (Central says not-found), `503` with `Retry-After`
   (timeout, throttle, transient 5xx), or `502` (authentication, unmapped
   connection, rejected redirect) — never a silent success.

### Enabling it per project

Self-heal is off by default and enabled one project at a time:

```
docker compose exec minerva_app_service uv run flask attachments central-fetch <PROJECT_ID> --enable
docker compose exec minerva_app_service uv run flask attachments central-fetch <PROJECT_ID> --status
docker compose exec minerva_app_service uv run flask attachments central-fetch <PROJECT_ID> --disable
```

Equivalent admin API: `PUT /admin/api/projects/<project_id>/attachment-central-fetch`
with `{"attachment_central_fetch_enabled": true|false}` (admin only, CSRF via
`X-CSRFToken`), and a per-row toggle in the admin Projects panel.

A project with no active `map_project_odk` connection fails closed: delivery
reports a configuration error rather than reaching for any other Central
server. There is no global or default connection.

### Config keys

| Key | Default | Meaning |
|---|---|---|
| `ATTACHMENT_FETCH_CONNECT_TIMEOUT_SECONDS` | `5` | Connect timeout for a request-path fetch from Central. |
| `ATTACHMENT_FETCH_READ_TIMEOUT_SECONDS` | `30` | Read timeout for the same. Deliberately tighter than `ODK_READ_TIMEOUT_SECONDS`, which is the sync-path value. |
| `ATTACHMENT_FETCH_MAX_SLOT_WAIT_SECONDS` | `1` | How long a request-path fetch may queue behind the shared ODK pacing interval before failing fast. Sync keeps sleeping out the full interval; a coder's image request must not occupy a worker doing that. |
| `ATTACHMENT_STORE` | `local` | `local` or `s3`. With `s3`, every key below is required and the app refuses to start without them — it never falls back to local disk silently. |
| `S3_SERVER` | _(unset)_ | Endpoint URL, e.g. `https://s3.ap-south-1.amazonaws.com`. |
| `S3_BUCKET` | _(unset)_ | Bucket name. |
| `S3_REGION` | derived | Derived from the endpoint host when it matches `s3.<region>.amazonaws.com`; otherwise required. |
| `S3_ACCESS_KEY_ID` | _(unset)_ | Secret. Environment only; never logged. |
| `S3_SECRET_ACCESS_KEY` | _(unset)_ | Secret. Environment only; never logged. |
| `S3_PREFIX` | `` | Optional key prefix inside the bucket, e.g. `digitva/`. |
| `ATTACHMENT_PRESIGN_EXPIRY_SECONDS` | `300` | Lifetime of a delivery presigned URL. |
| `SMARTVA_RUNS_KEEP_LOCAL_DAYS` | `0` | Days a *verified* SmartVA run directory stays on the VM after the run completed. `0` removes it as soon as the archive is verified. Ignored on the local store. |

Add these to the environment template alongside the existing ODK keys; the
values themselves belong only in the deployment's `.env` or secret store.

### Bucket provisioning checklist

Before setting `ATTACHMENT_STORE=s3`:

1. Create the bucket in `ap-south-1`, **private**, with **Block Public Access**
   fully enabled at both bucket and account level.
2. Turn **versioning on**. A replaced or mistakenly deleted object is then
   recoverable.
3. Default encryption: **SSE-S3 (AES256)**. Every upload also sets
   `ServerSideEncryption: AES256` explicitly.
4. **No lifecycle expiry on current object versions.** Attachments of retired
   submissions are the archive; nothing expires them. A noncurrent-version
   transition or expiry rule may be added later, but only deliberately.
5. Attach a least-privilege IAM policy to the application principal, scoped to
   this bucket (and prefix, when `S3_PREFIX` is used) and nothing else:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DigitVaAttachmentObjects",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::DIGITVA_BUCKET/*"
    },
    {
      "Sid": "DigitVaAttachmentListing",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::DIGITVA_BUCKET"
    }
  ]
}
```

   `s3:HeadObject` is covered by `s3:GetObject`. `s3:DeleteObject` is needed
   only so sync can remove a *superseded* object after the row already points
   at its replacement; no other code path deletes.

   The same bucket and the same IAM statements also cover the **SmartVA run
   archive** under the `smartva_runs/` prefix — Get/Put/Delete on the objects
   and List on the bucket is everything it needs, so no policy change is
   required. Those objects are never presigned, so nothing about the delivery
   path applies to them.

6. Backup scope: the bucket is now a primary data store. Include it in the
   backup plan alongside the database — versioning plus either cross-region
   replication or a periodic inventory/restore drill. `local_path` no longer
   points anywhere for `store_state='s3'` rows, so an app-server disk backup
   does not cover attachments after the cutover.

### Cutover runbook

Reversible up to the retention step; nothing is deleted by any tool.

1. **Provision** the bucket per the checklist and set the `S3_*` keys, leaving
   `ATTACHMENT_STORE=local`.
2. **Enable** the store: set `ATTACHMENT_STORE=s3` and restart
   `minerva_app_service minerva_celery_worker minerva_celery_beat`. The app
   refuses to start if a key is missing. From this point new sync downloads go
   to the bucket; rows still marked `local` keep serving from disk.
3. **Upload** the backlog:
   `flask attachments s3-upload --dry-run`, then
   `flask attachments s3-upload --workers 8`. Re-run until it exits `0`.
4. **Verify**: `python scripts/check_attachment_integrity.py --store s3`
   (or the panel's *Run integrity check* button, which records the same counts
   on a `va_sync_runs` row)
   must report `0` missing objects and `0` rows awaiting the cutover.
5. **Quarantine** the local copies:
   `flask attachments local-quarantine --dry-run`, then without the flag.
   Files move to `APP_DATA/<form_id>/media/.s3-uploaded/`; nothing is deleted.
6. **Retention**: leave the quarantined files for an agreed window (at least
   one full backup cycle) while watching delivery outcomes.
7. **Remove** them by hand, after a verified backup, e.g.
   `find data/*/media/.s3-uploaded -type f -delete`. This is deliberately not a
   command in the application.

Rollback before step 7: set `ATTACHMENT_STORE=local`, move the quarantined
files back, and restart. Rows marked `store_state='s3'` will need
`local_path`/`store_state` restored, so a rollback after a large upload is a
data operation, not a config change — which is why steps 4 and 6 exist.

### SmartVA Run Archive

A SmartVA run directory is a working area the SmartVA CLI needs while it runs.
Nothing in the app reads it afterwards, so with `ATTACHMENT_STORE=s3` the whole
directory is uploaded to the same bucket under
`smartva_runs/{project_id}/{form_id}/{form_run_id}/{relative path}` right after
the batch commits, verified against one listing of that prefix, and only then
removed from the VM. With the local store nothing changes: runs stay on disk.

These files hold full VA payloads. They are PHI: private bucket, SSE, and —
unlike attachments — **never presigned and never served to a browser**.

Where the state lives: `va_smartva_form_runs.archive_state`
(`local`/`archived`/`failed`/`absent`, indexed), `archive_key_prefix`,
`archived_at`, `archive_error_code`, `archive_file_count`, `archive_bytes`.
`disk_path` becomes NULL only after a verified archive lets the local copy go.

Operating it:

```
docker compose exec minerva_app_service uv run flask smartva archive-status
docker compose exec minerva_app_service uv run flask smartva archive-runs --dry-run
docker compose exec minerva_app_service uv run flask smartva archive-runs --delete-local
docker compose exec minerva_app_service uv run flask smartva archive-runs --form-id <FORM_ID> --limit 100
```

`archive-runs` is idempotent and resumable: an object already present at the
right size is verified rather than re-uploaded, and `--delete-local` is off by
default. It exits non-zero if any run failed. The equivalent admin action is
*Archive pending runs* in the Attachment Management panel, which queues the
bounded `run_smartva_run_archive` Celery task (200 run directories per press)
and records it on a `va_sync_runs` row.

Backlog to clear on first cutover: about 13.5k files / 279 MB across the
existing run directories. Nothing is deleted until its archive is verified, and
any failure leaves the directory in place with a short `archive_error_code`
(`upload_failed`, `verify_mismatch`, `store_unavailable`, `walk_failed`,
`local_delete_failed`) — retried by re-running the command.

Policy baseline: [SmartVA Generation Policy](../policy/smartva-generation-policy.md),
*Run Directory Archival*.

### What to watch

The admin **Attachment Management** panel (`/admin/panels/attachments`, or
`flask attachments overview`) puts everything below on one page: per-form counts
by `source_state`, `derivative_state`, `store_state` and
`local_fallback_state`, retired-submission rows, S3 upload progress, the
delivery counters, and the source error categories. It also offers per-form
attachment repair and the integrity check as bounded background runs. See
[the admin model](admin-and-setup.md#attachment-management-panel).

- The one structured log line per delivery:
  `attachment delivery outcome=<...> latency_ms=<...> sid=<...> form=<...> error=<...>`,
  with `outcome` one of `local`, `central_stream`, `central_redirect_followed`,
  `unavailable`, `error`. No URLs, query strings, headers, or payloads are logged.
- The matching in-process counters, `attachment_service.delivery_counters()`.
  A rising `central_stream` rate after the initial fill means the store is
  losing objects; any sustained `error` means a connection or redirect problem,
  not a missing attachment.
- `va_smartva_form_runs.archive_state`: `local` runs still hold a directory on
  the app server; `archived` runs do not once the keep-days window has passed;
  `failed` runs are the ones to retry. The panel's SmartVA run archive block
  shows these counts, the bytes still on the VM, and the last failure category.
- `va_submission_attachments.store_state`: `local` rows still hold a file on
  the app server; `s3` rows do not and have a NULL `local_path`.
- `va_submission_attachments.source_state` / `source_error_code`: `available`
  after an observed content response, `missing` when Central reports not-found,
  `error` with a category otherwise. A row already proved `available` is not
  downgraded by a transient failure.

## Logging

### Current logging implementation

Logging is configured in:

- [`app/logging/va_logger.py`](../../app/logging/va_logger.py)

Logging is wired into the app in:

- [`app/__init__.py`](../../app/__init__.py)

Current log outputs:

- `logs/requests.log`
- `logs/responses.log`
- `logs/errors.log`
- `logs/sql.log`
- `logs/celery_tasks.log`
- `logs/celery_slow_queries.log`

All high-volume logs use 6-hour rotation with bounded retention (56 files, ~14 days).

### Request abuse control

The app now applies a cache-backed temporary IP ban for repeated `405 Method
Not Allowed` responses on configured mutating methods.

Current behavior:

- tracked methods default to `POST` and `PATCH`
- qualifying `405` events are counted per IP inside a rolling window
- once the threshold is reached, the IP is temporarily blocked for a configured
  TTL
- blocked API/admin API requests receive JSON `403` responses with
  `Retry-After`
- blocked non-API requests receive a plain `403` response with `Retry-After`
- `/health` and `/static` remain exempt from the early ban check

### Request and response logging

The app logs:

- user identity when available
- client IP
- method
- path and query string
- request payload key summary with sensitive fields masked
- response metadata (`status`, `bytes`, `content_type`)
- shared request correlation id in both request/response logs and response header (`X-Request-ID`)

Masked request fields currently include values such as:

- `password`
- `csrf_token`
- `new_password`
- `va_current_password`
- `va_new_password`
- `va_confirm_password`

### Error logging

Unhandled exceptions are logged to `errors.log` with stack traces and request context.

### SQL and Celery slow-query logging

Slow SQL logging is event-based:

- web process: `logs/sql.log` (threshold `0.5s`, all statement types)
- Celery process: `logs/celery_slow_queries.log` (threshold `1.0s`, all statement types)

Celery task execution logs are written to `logs/celery_tasks.log` with task metadata and correlation fields.
Celery `ERROR`-level events are also mirrored into the shared `logs/errors.log`
sink so operational triage can use one consolidated error log across Flask and
Celery.

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

The repository now includes an outbound email subsystem for onboarding and
account recovery.

What exists today:

- Flask-Mail integration in [`app/services/email_service.py`](../../app/services/email_service.py)
- Celery task dispatch for verification and password-reset messages
- SMTP settings in [`config.py`](../../config.py)
- email verification and password reset templates under
  [`app/templates/emails`](../../app/templates/emails)
- Redis/cache-backed recipient suppression after permanent SMTP failures
  (configured via `EMAIL_SUPPRESSION_*`)
- explicit delivery kill switch via `EMAIL_DELIVERY_ENABLED`
- test config enforces `MAIL_SUPPRESS_SEND=True` so tests do not send real SMTP
- email link base URL resolves `MAIL_BASE_URL`, then `SERVER_NAME`, then
  `localhost:5000`, and is always given an `https://` scheme if it lacks one

Current implication:

- new-user onboarding can send both verification and password-setup emails
- password reset remains email-driven
- the email verification link now hands off to password setup for users who
  have not completed onboarding yet
- the post-login onboarding gate is a terms-acceptance page only; password
  creation happens in the password-reset step before login
- repeated permanent SMTP failures for a recipient are suppressed for a bounded
  TTL to avoid repeated bounce storms and queue churn

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

- no UI for infrastructure/admin setup
- logs are file-based, not centralized
- attachment and sync data are stored on local/shared disk paths
- live ODK behavior still depends on one shared Central instance being healthy,
  though the app now uses per-connection pacing and cooldown to reduce burst
  pressure

These constraints matter for any future move toward multi-project and multi-server onboarding.
