---
title: Runtime And Operations
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-25
---

# Runtime And Operations

## Summary

This document captures the current Python runtime, container setup, migrations, tests, logging, and adjacent operational features.

## Staging deployment baseline

Checked 2026-10-19: `digitvav3.causeofdeathindia.com` runs application source
`119384c72`, database head `b8d2f4a6c901`, and the Expo web export built from
`4527580c2`. The app, Celery worker and beat were rebuilt using the external
database and runtime-health overlays; the database, ingress and adjacent
services were retained. Static asset version is `20261019.filters1`.

The owner approved code only: no `DEMO01` project, synthetic reset flags or
weekly reset runs exist, and the weekly demo target is unset. Existing
`SADEMO` training configuration is separate and was preserved. Startup imported
zero translation sources and skipped thirteen previously installed sources.
Owner edits continued during validation: Hindi advanced from version34 to40,
inactive and `in_review`. Pre/post snapshots therefore differ; no older snapshot
was restored. Startup imported0/skipped13/written0, and browser checks made no
translation writes. The editor now excludes non-reference runtime choice keys
such as `language/en`, retaining canonical workbook/layer choices. The popup
names outstanding notes and distinguishes blank text, unaccepted machine drafts
and unsaved edits. Accept cannot discard a dirty draft; save/accept refreshes
current-row counts. Shared-list sibling cache refresh remains `digitva-xzdm`.
Browser checks verified
Interviewer selection, no-email user creation fields and ten-digit validation,
Add worker confirmation fields, and the mentoring-institute panel. No account
or grant was created by these checks. The missing-option filter exposes the
narration-language row and five DORIS choice-list rows; an orphan list opens
with editable options. The footer link opens the Expo coding interface.
`DIGITVA_ANDROID_APK_URL` points to the verified `android-v0.1.0` testing
release; the Help page renders that exact asset link. Physical native acceptance
remains pending.

Fresh pre-update backup: `digitvav3/db-backups/minerva/pg_dump_minerva_20261019T112139Z.dump`,
34,663,268 bytes, SHA-256
`e6142142f196b67bfdc59b7c54c7f51ed4310b45a2a9eeed2e4c085d124f1353`.
Remote object size was checked. Prior app/worker/beat images retain the
`rollback-pre-choicekeys-20261019` tag; no database downgrade was needed.

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
- **Session Timeout**: Sessions have a 30-minute inactivity timeout (`PERMANENT_SESSION_LIFETIME = 30 mins`). This is enforced via `session.permanent = True` on login. The stored expiry slides at most once per 60 s, so the idle timeout is 30 minutes measured to the minute (29-30).
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
  - **SmartVA engine stage** (`smartva_rs`): by default downloads the pinned,
    SHA-256-verified release tarball and extracts `smartva-rs` and
    `libsmartva_rust.so` from it; with `SMARTVA_RS_SOURCE=source`,
    `rust:1.90-slim-trixie` runs `cargo build --release --locked --bin smartva-rs --lib`
    in `vendor/smartva-analyze/rust`. Only the binary and the library leave the stage
  - **Runtime stage** (`runtime`): `python:3.13-slim`, copies `uv` and `.venv` from the build stages,
    `smartva-rs` to `/usr/local/bin/smartva-rs` and `libsmartva_rust.so` to
    `/usr/local/lib/libsmartva_rust.so` (outside the dev `.:/app` bind mount, so
    the dev app, worker and beat containers built from the image all have them)
- installs `postgresql-client`, `sox`, and `libsox-fmt-all` for audio conversion
- SmartVA installed as a uv path dependency (`vendor/smartva-analyze`)
- marks `boot.sh` executable
- exposes port `5000`
- `PATH` includes `/app/.venv/bin` so all Python entrypoints (`flask`, `celery`, `gunicorn`) work without `uv run`

Why the extra system packages exist:

- `postgresql-client` is needed for `pg_dump`/`psql` in DB backup and Celery beat startup
- `sox` and `libsox-fmt-all` handle AMR→M4A/AAC audio conversion (replaces `ffmpeg`)

### Image sources

The app, Celery worker, Celery beat and `doris_public_service` are built from
the same Dockerfile with the same args (`x-release-pins`), so they are one
image, `ghcr.io/drguptavivek/digitva-app`. Dev (`docker compose up`) builds it
from source. Servers never build ([policy](../policy/server-builds.md)): the
`Server images` workflow (`.github/workflows/server-images.yml`, native
`ubuntu-24.04-arm` runner, `linux/arm64`, Actions cache) pushes it tagged with
the full git sha (and `server-v*` tags), and `docker-compose.images.yml`
(layered last in production) replaces `build:` with
`image: ${DIGITVA_IMAGE_REGISTRY:-ghcr.io/drguptavivek}/digitva-app:${DIGITVA_IMAGE_TAG}`,
which has no default. `make prod-pull` / `scripts/deploy-server.sh` deploy it
([runbook](split-production-deploy.md)). `icd_api_rust_service` (opt-in, never
staging or production) still builds from `docker/icd11/Dockerfile`.
`make prod-build` and `prod-rebuild` are dev/emergency only.

### Compose setup

The local/container runtime is defined in [`docker-compose.yml`](../../docker-compose.yml).

Current services:

- `minerva_app_service`
- `minerva_db_service`
- `minerva_redis_service`
- `minerva_celery_worker` (Celery worker)
- `minerva_celery_beat` (Celery beat)
- `icd_api_service` (optional WHO ICD-11 API, Coding Tool, Browser, and DORIS; Rust in-process host, see [WHO ICD-11 service](#who-icd-11-service))
- `doris_public_service` and `digitva_ingress` (optional `icd11` profile; the public training service and same-origin path router)

Current behavior:

- local override (`docker-compose.override.yml`) runs Flask dev server on `0.0.0.0:5000`, mapped to host port `8051`
- the optional `icd11` profile runs WHO ICD API 2.6.0 with MMS 2026-01 English and DORIS 1.2.0; it is bound only to `127.0.0.1:8382`, with analytics disabled and a DORIS healthcheck (see [Local WHO ICD-11 API Runtime](../policy/icd11-local-api-runtime.md) and [WHO ICD-11 service](#who-icd-11-service))
- the same profile exposes its local public training entry at `127.0.0.1:8052` through `digitva_ingress`; production traffic must use this ingress for the DORIS Help route and API (see [DORIS COD Workflow](doris-cod-workflow.md))
- the app reaches the WHO API at `ICD11_API_BASE_URL=http://icd_api_service` inside Compose; assessment browsers use the authenticated DigitVA route described in [ICD-11 Embedded Coding Tool in Assessments](../policy/icd11-ect-production.md)
- the dev override now activates a dedicated development config via `FLASK_ENV=development`, which disables `Secure` session/remember cookies and strict HTTPS-only CSRF checks so login works on plain `http://localhost:8051`
- redis is bound to host port `6379`
- redis runs `--maxmemory 64mb --maxmemory-policy volatile-lru` and is shared by the Celery broker and result backend (db 0), Flask-Caching, flask-limiter and the authz grant cache. `volatile-lru` evicts only keys that have a TTL, so Celery's queue lists, `unacked` structures and `_kombu.binding.*` sets (no TTL) are never evicted while caches still shrink under pressure (`allkeys-lru` could drop queued tasks). Every cache-like key the app writes therefore needs an expiry: Flask-Caching calls pass a positive `timeout` (never `0`/`None`), the sweep locks use `set(..., ex=ttl)`, flask-limiter sets its counters' expiry itself, Celery results expire after the default `result_expires` (1 day; `task_ignore_result` is on), and the authz grant cache sets `ex=` on entries and on its `gv`/`uv:<user>` version keys (1 day, re-seeded with a random token when missing). If the broker side alone fills 64 MB, Redis refuses writes (`OOM`) rather than evicting queue data: raise `--maxmemory` then. Deploy note: an existing deployment keeps `allkeys-lru` until its Redis container is recreated from the new compose file (`docker compose up -d minerva_redis_service`; queued, unacknowledged tasks are lost on recreate, so drain the queues first outside dev); confirm with `redis-cli CONFIG GET maxmemory-policy`.
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
- celery worker has `cpu_shares: 128` (cgroup `cpu.weight` ~21 vs the app's 100) and is
  started as `nice -n 10 celery ... --concurrency=1 --max-memory-per-child=300000`
  (main and demo compose files; beads digitva-295w, digitva-g8iu). `cpu_shares` is the
  mechanism that keeps gunicorn on the 2-vCPU host: on staging (200 users, 4 min) p50
  coding.available was 142 ms worker paused, ~580 ms with `nice -n 10` alone, 252 ms with
  `cpu_shares: 128` (26.5 vs 24.8 req/s). `nice` is kept but has no effect across
  containers, since each container is its own cgroup and niceness only ranks processes
  inside it. The demo worker is also 128, against the demo app's 256. A hard `cpus` limit was rejected: it would slow the SmartVA drain when idle.
  Change it by recreating the container
  (`docker compose up -d --no-deps --force-recreate minerva_celery_worker`);
  `docker update --cpu-shares 0` does NOT reset the value. Check it with
  `/sys/fs/cgroup/system.slice/docker-<container id>.scope/cpu.weight` (~21 worker, 100 app).
- celery worker startup uses `--concurrency=1 --max-memory-per-child=300000`
  (KiB, ~293 MiB; owner set 250 MiB on 2026-10-22 and approved 300000 on
  2026-10-23 for the in-process SmartVA engine, bead digitva-5gsq): a task that leaves the pool child above
  the limit finishes, then the child is replaced by a fresh fork. The child
  keeps SmartVA's trained models (about +55 MiB), so SmartVA work peaks at
  236-240 MiB (measured before the lazy imports); the limit sits above that,
  so it catches only heavier tasks (exports, large syncs) and does not throw
  the models away after every SmartVA task
- `config.py` recycles a worker child mainly on memory:
  `worker_max_tasks_per_child` is 1000 (it was 100; a safety net for leaks
  memory does not show, owner 2026-10-23), and
  `worker_max_memory_per_child` is 300000 KB, the same as the flag above, so
  a worker started without the flag (the demo stack's) is capped too. With the
  100-task recycle, the worker idled ~1-4 s per recycle and rebuilt the
  SmartVA models. On a 6,932-case SmartVA backlog that was 216 s of a 599 s
  drain, and it ate most of the gain of running queued cases together
  ([SmartVA throughput](smartva-analysis.md#throughput), bead digitva-96ik)
- celery beat boots the app without blueprints: `scripts/wait-for-celery-beat-db.sh`
  exports `DIGITVA_REGISTER_ROUTES=0` and `make_celery.py` passes it to
  `create_app(register_routes=...)`. Beat only sends tasks by name; schedule
  seeding and `cleanup_stale_runs()` run as before. The worker keeps the
  routes for the email templates it renders
- all services run Python entrypoints directly (`flask`, `celery`, `gunicorn`) — no `uv run` wrapper needed

Current health checks:

- app: Python `urllib.request.urlopen('/health')` (no `curl`/`wget` in slim image)
- db: `pg_isready -U minerva`
- `icd_api_service`: `icd11-healthcheck` posts a one-line certificate to DORIS and needs `"stemCode":"BA41.Z"` back, so it is green only with the engine loaded
- `doris_public_service`: its own `/health` and the same DORIS call through `ICD11_API_BASE_URL`, so it turns unhealthy when the ICD service is down (`digitva-cfb1`; the container it replaced was OOM-killed with no restart policy while this check stayed green)

### Expo web export

Hosts never build the Expo web export (no Node on the host). It is published
as a release asset of DigitVA (`expo-web-v<date>`, a tarball of
`mobile/digitva-collect/dist` with `ui-strings`) with its SHA-256. The app
image's `expo_web` stage downloads the release pinned in `x-release-pins`
(`EXPO_WEB_TAG`, `EXPO_WEB_SHA256`) in `docker-compose.yml`, verifies the
checksum (a missing or wrong pin fails the build) and installs it at
`/opt/digitva/expo-client`, outside the `.:/app` bind mount;
`EXPO_CLIENT_DIST` points there. Dev (`docker-compose.override.yml`) serves
its own `npm run export:web` build from the checkout instead. To publish a new
export: run `Expo web export release` (`.github/workflows/expo-web-release.yml`,
`workflow_dispatch` with `publish=true` and `tag=expo-web-vYYYY.MM.DD.N`). It builds
the vendored WHO package, runs the tests and `npm run export:web`, tars `dist` with
a fixed order and mtime, refuses AppleDouble entries, and writes the `.sha256`. The
publish job creates the release (`--latest=false`). Then bump the two pins and run
`Server images`. No export is built on a developer machine.

### Android APK download

The signed APK is built and published by the GitHub CI workflow
(`.github/workflows/android-release.yml`, tag `android-v<version>`). Users get
it two ways, both from the public help page `/help/mobile-app` (linked from
every server page's footer and the help home):

- **GitHub releases page:** `DIGITVA_ANDROID_APK_URL`, normally
  `https://github.com/drguptavivek/DigitVA/releases/latest` (Android releases
  are marked Latest; web-export releases are published with `--latest=false`).
- **This server:** `/download/android` serves one release asset pinned in
  `x-release-pins` (`ANDROID_APK_TAG`, `ANDROID_APK_ASSET`,
  `ANDROID_APK_SHA256`), which the Dockerfile `android_apk` stage downloads and
  checks into `/opt/digitva/android` (`DIGITVA_ANDROID_APK_DIR`). Empty pins
  build an empty folder and the route answers 404; a partial pin fails the
  build. Bumping is an edit to the pins and a new `Server images` run.

### WHO ICD-11 service

`icd_api_service` is WHO's own `whoicd/icd-api:2.6.0` container, pinned by
digest (owner decision 2026-10-22: licensing for the Rust ICD host is
unresolved, so staging and production keep WHO's container). Port 80, host
binding `127.0.0.1:8382`, `ICD11_API_BASE_URL` unchanged; `saveAnalytics` is
off.

- `restart: always` and a 2 GB memory cap (the container was OOM-killed once
  and stayed down, `digitva-cfb1`).
- The healthcheck posts a one-condition DORIS certificate with the image's
  busybox `wget` and passes only when DORIS returns `BA41.Z`, so it is green
  only when the engine answers, not when the port is merely open.
  `doris_public_service` runs the same DORIS check through
  `ICD11_API_BASE_URL`.
- The Rust host `digitva-icd11-server` (`desktop/crates/digitva-icd11`,
  `docker/icd11/Dockerfile`, compiled from source) is opt-in only as
  `icd_api_rust_service` under the `icd11-rust` profile. It is not for staging
  or production until licensing is resolved, and it takes the same hostname and
  port, so never run both.

## Boot And Startup

Startup behavior is controlled by [`boot.sh`](../../boot.sh).

Current startup sequence:

1. retry `flask db upgrade` until DB is reachable
2. start Gunicorn on port `5000` with `--preload` and `GUNICORN_WORKERS`
   workers (default 1; the split production deploy sets 2 x 4 threads)

Current implication:

- schema migrations are applied automatically at container startup
- runtime is tightly coupled to the DB being available
- old-format live databases are expected to migrate forward via additive
  Alembic migrations rather than manual resets

### Startup imports

Every web and Celery process runs `create_app()` (gunicorn through `run.py`,
Celery worker and beat through `make_celery.py`). pandas, numpy, pyodk and
openpyxl are not imported at startup: modules import them inside the
functions that use them (`TYPE_CHECKING` for annotations), and
`app/utils/__init__.py` resolves its re-exported helpers lazily on first
access (PEP 562 `__getattr__`) instead of importing every helper.
`tests/test_startup_imports.py` fails if either entry point loads one of them
again. Measured 2026-10-22 (VmRSS of idle processes started from the tree
before and after the change, same container, two runs each): gunicorn worker
202 to 143 MB, Celery worker parent 213 to 154 MB and child 169 to 131 MB,
beat 214 to 155 MB.

## Process Memory

Each Python process's memory is mostly its import baseline, not app data.

`gunicorn --preload` imports the app once in the master, so the workers share
those pages copy-on-write; it helps only with 2+ workers. `app/__init__.py`
registers an `os.register_at_fork` hook for every fork (gunicorn workers, the
Celery prefork child and its replacements):

- before fork, `gc.collect()` then `gc.freeze()`: without the freeze each
  worker's garbage collector touches, and so copies, every inherited object,
  and preload saves nothing;
- in the child, every SQLAlchemy engine is `dispose(close=False)`d. After
  `import run` the master's pool already holds a connection, and two processes
  on one socket corrupt the protocol (`pool_pre_ping` does not catch that).
  The parent's idle pooled connection is ended when the child frees its copy
  and reconnects on its next checkout; the gunicorn master and the Celery main
  process do no DB work after fork. redis-py and kombu reset their own pools
  on a pid change.

`tests/test_process_startup.py` checks the pool reset and beat's route-less
app.

Measured 2026-10-22 (`digitva-345y`): VmRSS and Pss from `/proc/<pid>/status`
and `smaps_rollup`, containers from the same image on an isolated database and
Redis db, gunicorn `-w 2 --threads 4` as in the split deploy, after 20
requests. Absolute idle figures move by up to ~30 MB between runs on the
Docker VM under memory pressure.

| Process | Before RSS (Pss) | After RSS (Pss) |
| --- | --- | --- |
| gunicorn master | 30 MB (19) | 205 MB (87), holds the preloaded app |
| gunicorn worker, each of 2 | 224 MB (181) | 176 MB (87) |
| gunicorn total Pss, 3 processes | 381 MB | 261 MB |
| celery worker main | 225 MB (114) | 215 MB (111) |
| celery worker pool child, idle | 186 MB (111) | 180 MB (108) |
| celery beat | 225 MB (183) | 200 MB (161) |

Preload without the freeze measured the same 381 MB total Pss as before. A
200-submission `sweep_smartva_pending` (4 SmartVA batches, 200 results saved)
takes the pool child from 171 MB to 190-192 MB, before and after.
The in-process SmartVA engine (bead digitva-5gsq) adds its cached models:
the same kind of sweep then peaks near 240 MiB ([SmartVA Engine](#smartva-engine)).

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
- Tests run inside the application container using `uv run python -m pytest tests/`;
  the full suite runs in parallel with `-n 4` (pytest-xdist, one database per
  worker, see `docs/policy/test-harness.md`). The dev override raises the app
  container's memory limit to 3g for this; the production limit stays 1g.
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

## Station config signing key

The server Ed25519 key that signs offline station configs
(`app/services/station_config_service.py`; bundle spec 6.4) and the bundle
ingest receipts (`app/services/bundle_ingest_service.py`, bundle spec 5.6;
without it a real ingest answers 503 `station_config_unavailable` before
any record is applied, a `/validate` still runs).

| Setting | Where | Secret? |
| --- | --- | --- |
| `BUNDLE_SERVER_SIGNING_KEY_FILE` | app only: `/run/secrets/bundle_server_signing_key` (compose secret `bundle_server_signing_key`) | file is secret |
| `BUNDLE_SERVER_SIGNING_KEY_PATH` | compose host path of the secret: default `./private/bundle_server_signing_key` (DEVELOPMENT, inside the checkout); the prod make targets pass `/data/digitva-secrets/bundle_server_signing_key` (or the absolute path in `.env`) | - |
| `STATION_CONFIG_VALID_DAYS` | app (`.env`, optional, default 180): lifetime of an issued config | no |
| `BUNDLE_MAX_AGE_DAYS` | app (`.env`, optional, default 90): oldest bundle `created_at` the ingest accepts; keep a retired `PII_KEM_*` private key in `PII_KEM_PREVIOUS_PRIVATE_KEY_FILES` at least this long after a rotation (bundle spec 3.4) | no |

- Bundle ingest decrypts with the `PII_KEM_*` keyring of the app process
  (AAD label `digitva_bundle`), in memory only; the uploaded file is not
  kept (the 7-day ciphertext retention of bundle spec 5.6 is not built).

- File: one line, the base64url (no padding) 32-byte Ed25519 seed. Read once
  per process; never logged. Unset, unreadable or malformed, or (outside
  `TESTING`) the published test key (`FIXTURE_SIGNING_KEY_ID`): issuing a
  config answers 503 `station_config_unavailable` (logged without the key);
  the app still starts. Issuing also needs `DEVICE_PUBLIC_URL` (the config's
  `server_url`; empty: 503). `TestConfig` leaves it empty; tests point it at the
  TEST-ONLY `tests/fixtures/station_config/test_server_signing_key`.
- Generate: `make ensure-secrets` writes the development key (0600 via
  `umask 077`) when missing; `make ensure-secrets-prod` writes it to
  `PROD_BUNDLE_KEY_PATH` in a directory set to 0700 (as the PII key's),
  refusing a relative path or one under the checkout.
  Neither overwrites an existing file.
- Back it up apart from the database. Stations pin its public key at first
  import (bundle spec 6.4); a new key means re-importing a config on every
  station by hand. Rotation is not built.

## Registration identifier keys

Registration numbers (`map_death_identifier`, digitva-kzyp) are encrypted per
value by `app/utils/pii_crypto.py`: AES-256-GCM under a random data key per value,
the data key wrapped by a hybrid ML-KEM-768 + X25519 KEM. Policy and format:
[Death Registration Identifiers](../policy/death-registration-identifiers.md),
"Encryption at rest".

| Setting | Where | Secret? |
| --- | --- | --- |
| `PII_KEM_PUBLIC_KEY`, `PII_KEM_KEY_ID` | app, worker, beat (`.env`) | no |
| `PII_BLIND_INDEX_KEY` (64 hex chars) | app, worker and beat: `docker-compose.yml` passes it, and `config.py` `load_dotenv()` reads the bind-mounted `/app/.env` in every container that mounts the checkout; production start requires it in every process that boots the app. Not in DORIS (no checkout mount, image built without `.env`) | yes |
| `PII_KEM_PRIVATE_KEY_FILE` | app and worker only: `/run/secrets/pii_kem_private_key` | file is secret |
| `PII_KEM_PREVIOUS_PRIVATE_KEY_FILES` | rotation only; retired keys are read, never used to wrap | file is secret |
| `PII_KEM_PRIVATE_KEY_PATH` | compose host path of the secret. The compose default `./private/pii_kem_private_key` is the DEVELOPMENT key inside the checkout; the prod make targets pass `/data/digitva-secrets/pii_kem_private_key` (or the absolute path in `.env`), outside the checkout | - |
| `PII_BACKUP_MAX_AGE_HOURS` | app (`.env`, optional, default 24): max age of the dump `--confirm-backup` names for `flask pii ... --apply` and `flask smartva scrub-runs --apply`; older needs `--allow-old-backup` (logged) | no |
| `PAYLOAD_PII_SPLIT_ENABLED` | app and worker are passed it by `docker-compose.yml`, but a value in `.env` reaches every container that mounts the checkout (beat too) through `load_dotenv`; beat writes no payload. Optional, default `false`; `TestConfig` forces false. A process with it off refuses to read or write a payload version that has a side row (`PayloadSplitStateError`): payload writes store the sealed set in `map_payload_version_pii` and compare by `version_fingerprint` (PII slice 1b part II-A). **Keep false**: it is set true only in the release window right after `flask pii split-payloads --apply`, once the readers (part II-B, implemented) are deployed; see [pii-slice-1b.md](../kb/pii-slice-1b.md), "Release procedure" | no |
| `REGISTER_PII_SPLIT_ENABLED` | app and worker, by `docker-compose.yml`. Optional, default `false`; `TestConfig` forces false. Register writes seal the personal columns of `va_death_register` into `pii_sealed` and NULL the plaintext (PII slice 2 T1); a process with it off refuses to write a sealed row (`RegisterSplitStateError`) but still reads it. **Keep false** until the readers and the register backfill ship; see [pii-slice-2.md](../kb/pii-slice-2.md) | no |
| `IDENTIFIER_RATE_LIMIT` | app (`.env`, optional): per-user budget of requests that carry registration numbers (register, correct, write); a limiter string, default `30 per hour` | no |
| `IDENTIFIER_SEARCH_RATE_LIMIT` | app (`.env`, optional): per-user budget of registration-number searches (`identifier_number`); a limiter string, default `120 per hour` | no |

- **Request size.** There is no global `MAX_CONTENT_LENGTH` (ODK attachment and
  interview uploads need megabytes). The intake blueprint caps each route's body
  itself (`app/routes/api/intake.py`, `_body_limit`): 16 KB for every call that
  carries registration numbers (413 `payload_too_large`, checked from
  `Content-Length` and again while reading), and the reverse proxy caps the
  rest (`client_max_body_size 55m` in `deploy/ingress-routes.conf`). The same
  file gives `/api/v1/cases/export.csv` `proxy_buffering off` and
  `proxy_max_temp_file_size 0`, so the plaintext CSV stream is never buffered or
  spooled to ingress disk; `EXPORT_MAX_ROWS` (default 200000) caps its rows. A write
  names at most 50 identifier codes and no raw value over 256 characters.
- Production (`not debug and not testing`) refuses to start without a
  well-formed public key, key id and blind index key, and any process with
  `PII_KEM_PRIVATE_KEY_FILE` set refuses without a readable private key that
  matches the public key. `minerva_celery_beat` is never given the private key:
  no secret mount, and the checkout's `private/` is masked by an empty tmpfs
  (`docker-compose.yml`), since every app container bind-mounts the checkout
  as root. A process without `PII_KEM_PRIVATE_KEY_FILE` refuses to start in
  production when it can read a key file at a default path
  (`/run/secrets/pii_kem_private_key`, `/data/digitva-secrets/pii_kem_private_key`,
  `<checkout>/private/pii_kem_private_key`; `pii_crypto._refuse_stray_private_key`;
  a warning in debug). `doris_public_service` (internet-facing) mounts no
  checkout: it runs the image's code, built without `.env` and `private/`, so
  it holds neither key; it does not boot the main app.
  Development and test with no public key configured use throwaway keys per
  process, but only when every `PII_*` setting is empty: an empty public key
  beside any other `PII_*` setting refuses to start, naming the setting.
  `TestConfig` forces all of them empty whatever `.env` holds.
- **Generate** (once per environment, before the first deploy): `make ensure-secrets`
  does it for development only (private key `private/pii_kem_private_key`,
  0600, git-ignored, inside the checkout; public settings and blind key
  appended to `.env`). `make ensure-secrets-prod` (run by `make prod`,
  `prod-build`, `prod-rebuild`) writes the key to `PROD_PII_KEY_PATH`
  (default `/data/digitva-secrets/pii_kem_private_key`, directory 0700, file
  0600, owned by the deploy user) and refuses a relative path, a path under
  the checkout, and a key file still in `private/`. With the public
  key already in `.env`, it adds only a missing blind key and refuses if the
  private key file is missing; it never regenerates a key pair. Anywhere else:
  `python scripts/generate_pii_keys.py --private-file <path> --env-file <env>`
  (prints no key material, refuses to overwrite). Install the private key in
  the secret store and mount it as `PII_KEM_PRIVATE_KEY_PATH`.
- **Back up** the private key file and `PII_BLIND_INDEX_KEY` apart from the
  database, and keep every private key that wrapped rows in a retained database
  backup until those backups expire. **Loss of the private key is loss of the
  numbers**: the rows (type, has number, audit) remain, the values must be
  re-entered. A backup alone discloses no number. A restore into another
  environment with different keys leaves values unreadable there, by design.
- **Rotate**: generate a new pair (new key id), move the old private key into
  `PII_KEM_PREVIOUS_PRIVATE_KEY_FILES`, set the new public key and key id, restart
  app, worker and beat, then run `flask pii rewrap` in the app container (keyset
  batches, idempotent, logs counts and row ids only; the data ciphertext is not
  touched; covers the identifier, payload side, death register and audit rows). When it reports zero failures and no rows on the old key id, drop the
  old private key after the backup retention. Rotating `PII_BLIND_INDEX_KEY`
  is a separate job that recomputes every index with writes paused (not built).
- **Register seal CLI**: `flask pii seal-register` (app container) seals the
  death register's personal columns and the audit rows' sealed values, with
  `--apply`, `--verify`, `--strip` (after the 30-day hold), `--restore` and
  `--recompute-digests`; dry run by default, counts only, backup gate on every
  write, run with ODK sync paused. See [pii-slice-2.md](../kb/pii-slice-2.md),
  "Backfill, verify, strip, restore (T4)".
- **Record sealing** (PII slice 1b; part II-A wires the payload writers
  behind `PAYLOAD_PII_SPLIT_ENABLED`, off by default;
  [pii-slice-1b.md](../kb/pii-slice-1b.md)): `seal_record` / `open_record`
  seal all fields of one record (a payload version, later a register row)
  under one data key, with the same stored formats, so `rewrap_dek` re-wraps a
  record unchanged. Sealing needs only the public key; with the flag on a
  payload writer also opens records (the revision carry, the enrichment
  write, the section-cache invalidation), so the app and the worker need the
  private key (decision 10), never beat. Unwrapped data keys
  are cached on `flask.g` (one request or job app context, at most
  `DEK_CACHE_MAX` = 256, `clear_dek_cache()` between batches, never
  persisted); the private key objects are built once per process.
- **Blind-index classes**: `subkey(class)` = HKDF-SHA256 of
  `PII_BLIND_INDEX_KEY` with info `digitva-pii-bidx/v1/<class>` (64 bytes);
  `class_index(class, value)` = HMAC-SHA-512 under it. Classes: `phone`,
  `abha_number`, `abha_address`, `payload-fp` (the payload fingerprint
  digest). No Aadhaar class. Registration numbers keep `blind_index` (raw key
  plus type-id context). Rotating the blind key changes every class index and
  every `pii_digest`, so they are recomputed with it.

## Attachment Delivery

### Two copies, and which one is read

DigitVA keeps its **own permanent copy** of every attachment — originals and the
MP3 derivatives it makes — and that store is the read path for
`/api/v1/attachments/<storage_name>` (the old `/vaform/attachment/<storage_name>`
is kept for pages rendered before the change). ODK Central keeps its own copy and remains
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
| `S3_PREFIX` | `` | Optional key prefix inside the bucket, one per environment sharing it, e.g. `staging/`. Normalized to one trailing slash (`staging` and `/staging/` both become `staging/`). Applies to attachments, backups, SmartVA archives and exports. Fix it before the first upload: objects are not moved when it changes. |
| `ATTACHMENT_PRESIGN_EXPIRY_SECONDS` | `300` | Lifetime of a delivery presigned URL. |
| `ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES` | `10` | Interval of the `run_attachment_s3_upload` beat sweep. Seeds a `celery_intervalschedule` row; a value outside 1–1440 logs a warning and falls back to the default, and a changed value repoints the existing beat row rather than adding a second one. |
| `SMARTVA_RUNS_KEEP_LOCAL_DAYS` | `0` | Days a *verified* SmartVA run directory stays on the VM after the run completed. `0` removes it as soon as the archive is verified. Ignored on the local store. |
| `DB_BACKUP_DAILY_TIME` | `01:30` | UTC time of day for the nightly database dump. Seeds a `celery_crontabschedule` row; an unparseable value logs a warning and falls back to the default. |
| `DB_BACKUP_KEEP_DAILY` | `30` | How many dumps to keep in the `db-backups/` prefix (or in `DB_BACKUP_LOCAL_DIR`). A count, not days. Clamped to at least 1. |
| `DB_BACKUP_LOCAL_DIR` | `<repo>/dailybackups` | Where a dump goes on `ATTACHMENT_STORE=local`. Unused on the S3 store, where the VM keeps no dump at all. |
| `DB_BACKUP_TMP_DIR` | system temp | Scratch space for one dump on its way to the bucket. Removed in a `finally`; never accumulates. |
| `DB_BACKUP_TIMEOUT_SECONDS` | `1800` | Hard stop for one `pg_dump`. A run that hits it is a hung connection, not a slow dump. |
| `EXPORT_RETENTION_HOURS` | `24` | How long a data-manager CSV export lives in the `exports/` prefix (or under `APP_DATA/exports/`) before the nightly prune deletes it. Clamped to at least 1. |

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

   The same statements also cover the **database backups** under the
   `db-backups/` prefix. That prefix is the one place a **lifecycle rule** is
   appropriate: bucket versioning keeps a noncurrent version of every pruned
   dump, so expire noncurrent versions there after ~30 days. Do not scope such
   a rule to the attachment or `smartva_runs/` prefixes — those hold primary
   data. See [backup.md](backup.md).

   The same statements also cover the **data-manager CSV exports** under the
   `exports/` prefix. These are the only keyed objects that are ever presigned
   — an export is derived data a data manager asked for, delivered as a
   short-lived `attachment` download — and the only ones DigitVA deletes on a
   clock (`EXPORT_RETENTION_HOURS`, default 24 h). A **lifecycle rule** is
   appropriate here too, and more so than for backups: expire noncurrent
   versions under `exports/` after a few days, since versioning would otherwise
   keep a noncurrent copy of every pruned export forever. See
   [data-manager-dashboard.md](data-manager-dashboard.md), *Exports*.

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
3. **Upload** the backlog. Nothing has to be done by hand: the sweep seeded in
   step 2 clears it at 500 blobs every `ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES`.
   Press *Upload backlog to S3 now* on the Attachment Management panel to start
   immediately, or run `flask attachments s3-upload --workers 8` (or
   `--as-task`, which hands the same work to the sweep) from a shell. Whichever
   path, watch the panel's **awaiting S3 upload** count fall to `0`; the latest
   sweep's status and uploaded count sit beside it, so no SSH session is needed
   to follow the cutover. A sweep that reports `partial` names how many rows
   failed; `flask attachments s3-upload` is the view that names *which*.
4. **Verify**, once the awaiting count is `0`:
   `python scripts/check_attachment_integrity.py --store s3`
   (or the panel's *Run integrity check* button, which records the same counts
   on a `va_sync_runs` row)
   must report `0` missing objects and `0` rows awaiting the cutover.
5. **Quarantine** the local copies:
   `flask attachments local-quarantine --dry-run`, then without the flag — or
   the panel's *Quarantine uploaded local files* button, which queues
   `run_attachment_local_quarantine` and records it on a `va_sync_runs` row.
   Quarantine is manual-trigger only and is never scheduled.
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

### SmartVA Engine

SmartVA runs on the pure-Rust `smartva-rs` engine (owner decision
2026-10-22), a drop-in for the Python `smartva` command line: same flags,
same input CSV, same four-folder CSV output tree, so prep and result parsing
are unchanged. Python SmartVA stays installed as the rollback.

Hosts never compile it. The app image downloads the pinned release asset of
[drguptavivek/SmartVA-Analyze-rust](https://github.com/drguptavivek/SmartVA-Analyze-rust)
(`v3.0.2`, `smartva-rs-linux-arm64.tar.gz` or `-linux-x86_64.tar.gz` by build
architecture) and verifies its SHA-256; an unset or wrong pin fails the build.
The pins are `x-release-pins` in `docker-compose.yml`, the one place to bump.
`SMARTVA_RS_SOURCE=source` in `.env` compiles `vendor/smartva-analyze/rust`
instead, for developers only (it made the staging host unresponsive).
`smartva-rs --version` in the image reports
`SmartVA-Analyze 3.0.1-rust (smartva-rust 3.0.2)`: the algorithm mirrors
upstream SmartVA-Analyze 3.0.1, the crate is 3.0.2.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SMARTVA_ENGINE` | `rust` | `rust` or `python`. Any other value fails the batch with an `execution` failure row. |
| `SMARTVA_RS_BIN` | `/usr/local/bin/smartva-rs` | Path of the binary built into the image. |
| `SMARTVA_RS_LIB` | `/usr/local/lib/libsmartva_rust.so` | The rust engine runs in-process through this library (same release tarball as the binary). Empty runs the binary as a subprocess instead. |

- With `rust` and no file at `SMARTVA_RS_LIB` (or, with `SMARTVA_RS_LIB=""`,
  no executable at `SMARTVA_RS_BIN`), the run fails with a
  failure detail naming the path and the rollback; it never falls back to
  Python silently, so the engine recorded on the run is the one that ran.
- Each `va_smartva_runs.run_metadata` records
  `"smartva_engine": {"name": "rust"|"python", "version": ...}`: the loaded
  library's own `smartva_version()` when `SMARTVA_RS_LIB` is in use, else
  `smartva-rs --version`, or the installed `smartva` package; `null` when it
  cannot be read. Both rust sources print the same string. A library older
  than 3.0.2 has no `smartva_version()`; the worker logs a warning and reads
  the binary instead.
- `SMARTVA_CHARTS=1` passes `--charts True` to `smartva-rs` (else
  `--no-charts`). Charts are debug-only; the slim image ships no system fonts
  for the Rust chart renderer, so expect chart drawing to need fonts added.
- The in-process engine keeps the trained tariff models in each worker child
  (about +55 MiB RSS, see
  [SmartVA throughput](smartva-analysis.md#throughput)), so
  `--max-memory-per-child` must leave room for it: a child recycled after
  every task pays the ~100 ms model build again on its first run. From
  smartva-rust 3.0.2 every C entry point catches a Rust panic and returns it
  as an error code and message, so a panic fails that one run (an `execution`
  failure row with the panic text) and the worker child keeps going; the
  model cache's lock ignores poisoning so later runs still score.
- Rollback to the subprocess: set `SMARTVA_RS_LIB=` (empty) in `.env` and
  restart `minerva_app_service`, `minerva_celery_worker` and
  `minerva_celery_beat`.
- Rollback: set `SMARTVA_ENGINE=python` in `.env` and restart
  `minerva_app_service`, `minerva_celery_worker` and `minerva_celery_beat`. No
  data change is involved; results already generated stay as they are.

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
- `logs/grants.log`
- `logs/slow_requests.log`
- `logs/doris_calls.log` (only with `DORIS_CALL_LOG=1`; daily rotation, 7 files; see `docs/current-state/doris-cod-workflow.md`)

All log files rotate every 6 hours, each rotated file is gzipped (`<name>.log.<UTC timestamp>.gz`), and 840 rotated files (210 days) are kept before the oldest is deleted (`LOG_BACKUP_COUNT` in `app/logging/va_logger.py`). Database audit records are kept permanently.

### Slow request log

`logs/slow_requests.log` gets one `event=slow_request` line for every request (static and `/health` excluded) that takes at least `SLOW_REQUEST_LOG_MS` ms (default 300): `method`, `endpoint`, `rule` (the route pattern, `-` for a 404), `status`, `duration_ms`, `sql_count` and `sql_ms`. It carries no user, query string, payload or case id, because `rule` is the pattern rather than the path; the line's `request_id` ties it to `requests.log`. Count slow requests per route: `zcat -f logs/slow_requests.log* | grep -o 'rule=[^ ]*' | sort | uniq -c | sort -rn`.

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

## Generated Form Artifacts

`GET /api/v1/instruments/<code>/definition` gzips the body itself (once per
cached entry) when the client sends `Accept-Encoding: gzip`, with
`Content-Encoding: gzip`, `Vary: Accept-Encoding` and its own ETag
(`"<sha256>.gz"`). A reverse proxy's gzip skips a response that already has a
`Content-Encoding`, so nothing is compressed twice; do not configure a proxy
to decompress and keep the header. `X-Definition-SHA256` is always over the
uncompressed JSON.

The composed form definition the server serves,
`app/data/who-va-2022.composed.json`, is generated from the vendored WHO
package and DigitVA's extensions. Rebuild it after any change under
`vendor/who-va-2022` (a question, label, rule or extension):

```bash
cd tooling/who-va-2022 && npm run build:composed-instrument
```

The build fails unless the tagged definition reproduces the package's own
composition for all 32 extension subsets, and prints the new `version`. Commit
the file; the server records the version the first time it serves it. Node runs
on the host, not in the app image. Details: "Form definition from the server" in
`docs/policy/field-data-collection.md`.

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
- demo coding cleanup every 15 minutes
- submission analytics MV refresh every 1 hour
- database backup daily at `DB_BACKUP_DAILY_TIME` (default `01:30` UTC), a
  crontab schedule rather than an interval because the time of day matters —
  see [backup.md](backup.md)
- notification purge daily, `purge_notifications_task`
  ([`app/tasks/notification_tasks.py`](../../app/tasks/notification_tasks.py)):
  deletes `map_user_notifications` rows older than 30 days, 5000 per statement,
  one short transaction per batch, until none are left. Never raises; a missed
  day only lengthens the next run. Redis keys `digitva_msg:last:<user_id>`
  (5-minute TTL, config `NOTIFICATION_CACHE_PREFIX`) are a cache only.
- sign-in IP wipe daily, `wipe_sign_in_ips_task`
  ([`app/tasks/security_event_tasks.py`](../../app/tasks/security_event_tasks.py)):
  one UPDATE removes `detail.ip` from `web_sign_in` events in
  `auth_security_events` older than `SIGN_IN_IP_RETENTION_DAYS` (210); the
  event is kept. Idempotent, never raises, logs a count only. Beat row
  "Sign-in IP wipe — daily" is seeded at worker startup like the notification
  purge.
- web intake upload purge daily, `purge_web_intake_uploads_task`
  ([`app/tasks/web_intake_upload_tasks.py`](../../app/tasks/web_intake_upload_tasks.py)):
  `web_intake_attachment_service.purge_expired_uploads` deletes uploads of open
  drafts untouched for 30 days and uploads no answer references after 30 days
  (never one a submission holds), 500 files per transaction, at most 20
  transactions per run; per batch it locks the case rows then the draft rows
  (`SKIP LOCKED`), removes the objects, deletes the rows and commits, one
  `draft_attachments_purged` audit row per draft per batch (actor: the draft's
  interviewer). Never raises, logs counts only. Beat row "Web intake upload purge — daily" is seeded at worker
  startup like the sign-in IP wipe.
- attachment S3 upload sweep every `ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES`
  (default `10`), `run_attachment_s3_upload` — copies up to 500 attachment
  blobs per sweep into the bucket and verifies each one. It is left scheduled
  permanently on every deployment: a sweep costs one indexed count query when
  `ATTACHMENT_STORE` is not `s3` or the backlog is empty, and keeping it on
  means any row that later ends up with `store_state='local'` — a restored
  backup, a manual fix — is copied back into the bucket without anyone having
  to notice. A scheduled no-op writes no `va_sync_runs` row (144 empty rows a
  day would bury the sync history); a sweep started from the admin panel
  always leaves one, because someone pressed a button and is owed an answer.
  Sweeps are serialised on a Redis key so a scheduled sweep and a press never
  work the same rows. `run_attachment_local_quarantine` exists as the manual
  counterpart and is **never** scheduled — moving a verified local copy aside
  is the step before an operator deletes it by hand.

Current SmartVA background run:

- `run_smartva_for_submission` ([`app/tasks/sync_tasks.py`](../../app/tasks/sync_tasks.py))
  is queued by `smartva_service.queue_smartva_after_commit` (a session
  `after_commit` hook, dropped on rollback, as the KPI recount) when a web or
  device interview, a changed revision or a supervisor's choice puts a case in
  `smartva_pending`, and by the coding page's Run SmartVA / Regenerate button.
  `va_smartva_run_pending` / `generate_all_pending` are not scheduled and do
  not reach web forms. One case takes a few seconds with the SmartVA binary
  (2.6 s measured on the dev stack), well inside the task's 300 s soft limit.
- Redis key `smartva-run:<va_sid>` (`queued` then `running`, TTL 30 minutes,
  cleared by the task on every exit) is the only state the coding page's
  status panel reads beyond `va_smartva_results`.
- the task is idempotent: an active result for the current payload version is
  skipped unless queued with `regenerate`.
- `sweep_smartva_pending` (same module) is the safety net, run by beat every
  30 seconds (periodic task "SmartVA pending sweep — every 30 seconds", seeded
  idempotently by `ensure_smartva_sweep_scheduled` at celery start, interval
  `every=30 seconds`, `expire_seconds=25` so ticks queued behind a busy worker
  are dropped instead of piling up). It first takes the Redis lock
  `digitva:lock:smartva-sweep` (`SET NX EX 780`, token value, released only
  while still its own; TTL above the task's 720 s hard limit), so a run longer
  than 30 s is never overlapped: a tick that finds the lock returns at once.
  Then one indexed query (`va_submission_workflow.workflow_state =
  'smartva_pending'`, joined to `va_submissions` for the form, confirmed
  duplicates excluded, at most 1000 rows read) finds the work; an empty sweep
  stops there and starts no SmartVA process. Sids with an `smartva-run:<sid>`
  marker belong to the per-completion queue and are skipped. The rest, at most
  200 per tick, are marked `running` (`smartva-run:<sid>`, cleared after their
  form's run in a `finally`) so the panel shows it, and go per form to `generate_for_form(form, target_sids=...,
  trigger_source='smartva_sweep')`, which batches by `SMARTVA_BATCH_SIZE` with
  the inter-batch sleep, and the sweep commits per form; one form's failure is
  logged and the next form still runs. A recorded SmartVA failure already moves
  the case to `ready_for_coding`; a sid still `smartva_pending` after its run
  (a crashed batch, a result that already exists) gets the Redis key
  `smartva-sweep-skip:<sid>` for 10 minutes, so it is not re-run every 30 s.
  Occupies one worker slot while it runs.
- `apply_bundle_pending_coding` (same module) applies offline bundle coding
  results held `pending` (`va_bundle_pending_coding`, bundle spec 5.5) once
  their case has left `smartva_pending` and `attachment_sync_pending`: beat
  every 60 seconds (periodic task "Bundle pending coding applier — every 60
  seconds", `expire_seconds=55`, seeded by `ensure_smartva_sweep_scheduled`
  at celery start), under the Redis lock `digitva:lock:bundle-pending-coding`
  (`SET NX EX 360`). One indexed query takes at most 50 held rows, oldest
  first; each is applied as the ingest would (the coder's allocation, then
  the coder writes; `bundle_ingest_service.apply_pending_coding`) and the
  reports that named it pending are rewritten. The worker holds no server
  signing key, so it clears those reports' stored receipts and
  `GET .../receipt` signs the current report on request (deterministic, not
  stored). An ICD-11 DORIS final (`doris_pending`) is reprocessed here first:
  `process_certificate` against the WHO service and a process proof minted
  for the actor's allocation, then the online DORIS final save. A coder busy
  with another case, or the WHO service down or not configured, leaves it
  pending; any other refusal ends it `rejected` with its code. An applied
  row gets the ingest's `station_record` case audit row (first bundle's
  device and config, the station's current custodian).
- A bundle `/validate` dry run runs inside `smartva_service.queue_suppressed`:
  no SmartVA marker or run for a case it touched, since everything is rolled
  back. It can consume death-number sequence values (not transactional).

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

### Training & demo project (TRN01)

`DIGITVA_TRAINING_PROJECT_ID` defaults to `TRN01` (owner 2026-10-22; set it
empty to turn training off) and enables `flask
training-demo`, the Training sessions panel and the sign-in onboarding
redirect. Nothing is scheduled and nothing is reset or deleted: sessions and
their cases are retained. Enabling needs `flask training-demo setup` once, and
the source ODK form (`UNSW01NC0101`) must exist with at least 200 consented
cases; creating a session copies 200 payloads, their attachments (same bytes,
new storage names, in whichever store is selected) and writes them in one
transaction.

Onboarding adds one hook after the terms check
(`training_demo_onboarding` in `app/__init__.py`): browser GET page loads only,
one indexed query per login session, remembered in the session either way.
Disabled when the setting is empty.

Reporting: DM and admin KPI views are scoped by project like any other project,
so TRN01 appears where DEMO01 appears. A coder's all-projects output summary
(`coder_dashboard_service.get_coder_output_summary`) excludes TRN01 unless the
project is asked for by id.

The trainer report (`/data-management/training/<code>`) is read-only: seven
aggregate queries per view (cases, participants, four staff counts, and the
session lookup), no ODK or filesystem work, and the cause mapping reads two
files under `resource/` once per process. The bulk add reads `va_users` with a
sequential scan (no created-at or created-by index; the table is small) and is
bounded to 200 rows per request; a bulk apply runs its grant checks and writes
per user inside one transaction under the session row lock.

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
- email link base URL resolves `PUBLIC_BASE_URL`, then `SERVER_NAME`, then
  `localhost:5000`, and is always given an `https://` scheme if it lacks one
- in production (`Config`, i.e. neither `DEBUG` nor `TESTING`) `create_app`
  sets Flask's `TRUSTED_HOSTS` to the `PUBLIC_BASE_URL` host plus `localhost` and
  `127.0.0.1` (container healthcheck), via `trusted_hosts_for` in
  [`config.py`](../../config.py); any other `Host`/`X-Forwarded-Host` gets a 400,
  and a missing `PUBLIC_BASE_URL` stops the app at startup. Development
  (`FLASK_ENV=development`) and tests accept any host
- similarly, production requires `CAPTCHA_HMAC_KEY` (signs the login page's
  proof-of-work challenge, see docs/current-state/workflow-and-permissions.md
  "Login Flow"); development/test derive a key from `SECRET_KEY` instead

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

## Machine translation of UI strings

The Celery task `app.tasks.ui_string_tasks.machine_translate_ui_strings` calls Azure Translator (`AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION`, `AZURE_TRANSLATOR_ENDPOINT`). A Redis lock allows one run at a time and Redis keeps the last run's counts for the admin page. See `docs/policy/ui-strings.md`.
