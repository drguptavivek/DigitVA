---
title: Installation
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-19
---

# Installation

## Prerequisites

- Docker and Docker Compose (v2+)
- Git with submodule support
- 2 GB minimum disk for Docker images, 5+ GB recommended for data
- Environment file (`.env`) with required secrets (see below)

## Quick Start

```bash
# 1. Clone with submodules
git clone --recurse-submodules <repo-url>
cd DigitVA

# 2. Create .env file
cp .env.example .env
# Edit .env with your secrets (see Environment Variables below)

# 3. Build and start
docker compose up -d

# 4. Seed the database (first time only)
docker compose exec minerva_app_service flask seed run
```

This gives you a running app with:
- testadmin@digitva.com / Admin@123 (admin user)
- WHO_2022_VA form type registered
- All 414 fields + 1196 choice mappings loaded
- No test submissions — clean slate

## Environment Variables

Required in `.env`:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask secret key (random string) |
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_DB` | PostgreSQL database name |

The following are auto-configured by docker-compose:

| Variable | Value | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://...@minerva_db_service:5432/...` | Internal Docker network |
| `REDIS_URL` | `redis://minerva_redis_service:6379/0` | Internal Docker network |
| `CELERY_BROKER_URL` | `redis://minerva_redis_service:6379/0` | Internal Docker network |

## Docker Architecture

### Multi-stage Build

The Dockerfile uses a two-stage build:

1. **Builder stage** — `python:3.13-slim` + uv binary, runs `uv sync --frozen --no-dev` to create the virtual environment
2. **Runtime stage** — `python:3.13-slim`, copies only the `.venv` from the builder. No uv binary, no build artifacts in the final image.

System packages in the runtime image:

| Package | Purpose | Size |
|---|---|---|
| `postgresql-client` | `pg_dump`, `psql` for DB backups and health checks | ~15 MB |
| `sox` + `libsox-fmt-all` | AMR → MP3 audio conversion | ~80 MB |

### Services

| Service | Purpose | Port |
|---|---|---|
| `minerva_app_service` | Flask/Gunicorn web application | 8051 → 5000 |
| `minerva_db_service` | PostgreSQL 17 database | Internal |
| `minerva_redis_service` | Redis for Celery broker | 6379 |
| `minerva_celery_worker` | Background task processing | Internal |
| `minerva_celery_beat` | Periodic task scheduler | Internal |

### Volume Mounts

| Mount | Purpose |
|---|---|
| `.:/app` | Source code (dev live reload) |
| `/app/.venv` (anonymous) | Preserves image venv from host mount |
| `pgdata_minerva` (named) | PostgreSQL data persistence |

### Override for Development

`docker-compose.override.yml` automatically enables:
- Flask debug mode and auto-reload
- Flask dev server instead of Gunicorn

## SmartVA Integration

SmartVA-Analyze is included as a git submodule at `vendor/smartva-analyze`. It installs automatically as a uv path dependency — no manual step required.

GUI-only dependencies (`wxpython`, `tornado`) are excluded via `[tool.uv] exclude-dependencies` in `pyproject.toml`.

To update the SmartVA submodule:

```bash
git submodule update --remote vendor/smartva-analyze
uv lock  # re-resolve deps
docker compose build
```

## Dependency Management

All dependency management uses **uv**:

| Task | Command |
|---|---|
| Add a dependency | `uv add <package>` |
| Remove a dependency | `uv remove <package>` |
| Sync dependencies | `uv sync` |
| Run Python command in container | `docker compose exec minerva_app_service <command>` |

**Important**: Python commands run inside Docker containers. The venv is baked into the Docker image and preserved via an anonymous volume. Do not run Python directly on the host.

## Seeding and Test Data

### Seed only (clean start)

```bash
docker compose exec minerva_app_service flask seed run
```

Creates: admin user, WHO_2022_VA form type, field + choice mappings. No submissions.

### Restore full test data

```bash
./scripts/restore-test-db.sh
```

Resets the DB schema → restores test data → runs migrations → seeds testadmin.

Test data includes:
- 5 sites with 1,081 total forms (474 coded, 607 remaining)
- 1 test admin, 5 test coder users (password: Aiims@123)

## Database Backups

Backups use `pg_dump` (custom format) via the app container:

```bash
# Create backup
docker compose exec minerva_db_service pg_dump -U minerva minerva -F c -f /tmp/backup.dump
docker compose cp minerva_db_service:/tmp/backup.dump ./backup.dump

# Restore backup
docker compose exec minerva_db_service pg_restore -U minerva -d minerva -c /tmp/backup.dump
```

The app also runs automatic backups via the backup service (keeps last 10).

## Production Notes

Three setups share `docker-compose.yml`:

| Setup | Files | Command |
| --- | --- | --- |
| Dev | `docker-compose.yml` + `docker-compose.override.yml` (auto-loaded) | `make dev` |
| Single-host prod (bundled PostgreSQL 17 container) | `docker-compose.yml` only | `make prod` |
| Split prod (PostgreSQL on its own host) | `docker-compose.yml` + `docker-compose.external-db.yml` | `make prod` |

`make prod` selects the split overlay by itself when `/data/digitva-db.env`
exists (override the path with `PROD_DB_ENV=`). Prod hosts must never run a
bare `docker compose up`: that auto-loads the dev override.

Split prod expects on the app host:

- `/data/digitva-db.env` (mode 0600): `DATABASE_URL=postgresql://<user>:<password>@<db-ip>:5432/<db>?sslmode=verify-full&sslrootcert=/etc/digitva-db/ca.crt`.
  Compose interpolates it, so a `$` in the password must be written `$$`.
- `/etc/digitva-db/ca.crt`: the database server's public certificate, mounted
  read-only at the same path into app, worker, beat and DORIS.
- `/etc/digitva-app/tls/server.crt` and `server.key`: the `digitva_ingress`
  nginx serves HTTPS with them on port 8000 for the reverse proxy and routes
  the public DORIS demo and the clinical app (Split Production TLS).
- `APP_BIND_IP` in `.env`: the private address the app publishes port 8000 on
  (defaults to `127.0.0.1`). Never `0.0.0.0`: Docker publishes ports around the
  host firewall, so only the cloud security group (port 8000 from the reverse
  proxy alone) and this binding keep the app private.
- No `COMPOSE_PROFILES` needed: the split overlay always starts the local WHO
  ICD-11 API, the public DORIS demo and its ingress (on a single host they
  still need `COMPOSE_PROFILES=icd11`).
- `ATTACHMENT_STORE=s3` and the `S3_*` keys in `.env` when attachments live in
  a bucket (template in `.env.example`). Production then refuses to start if
  one is missing, rather than writing attachments to the app host's disk.
- `PUBLIC_BASE_URL=https://<public hostname>` in `.env`. Production refuses to
  start without it. From it the app derives `TRUSTED_HOSTS` (the public host
  plus `localhost` for the healthcheck; any other `Host` header gets a 400),
  the WebAuthn RP ID and origin, the device-enrolment URL and email links. The
  reverse proxy must pass `Host $host`. Passkeys are bound to the RP ID, so
  ones registered under a different hostname stop working.

The bundled `minerva_db_service` is parked in a profile there and never starts;
`DATABASE_URL` missing is a hard error, never a silent fallback to it.
Certificate paths, issuing (`scripts/make-tls-cert.sh`) and copying the
public certificates between hosts: [Split Production TLS](split-production-tls.md).
Deploying a release there: [Split Production Deploy Runbook](split-production-deploy.md).
`scripts/manual-db-dump.sh` and `manual-db-restore.sh` exec into
`minerva_db_service` and do not apply to split prod.
