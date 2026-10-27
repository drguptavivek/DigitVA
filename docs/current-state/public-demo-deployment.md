---
title: Public Demo Deployment Runbook
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-27
---

# Public Demo Deployment Runbook

How to run the public demo (policy: [public-demo.md](../policy/public-demo.md),
sections 1, 8a and 9; design: `.tasks/2026-10-22-public-demo.md`) beside the
split production of [Split Production Deploy Runbook](split-production-deploy.md).
Placeholders (`<APP_PRIVATE_IP>`, `<DB_PRIVATE_IP>`, `<BACKEND_TLS_NAME>`) are
as in [Split Production TLS](split-production-tls.md). Run each step by hand.

```
Browser ─HTTPS 443─► DMZ proxy (nginx, public TLS for demo.causeofdeathindia.com)
                       │  appends X-Forwarded-For, HTTPS :8001, verified as <BACKEND_TLS_NAME>
                       ▼
App host:  demo_ingress ─► demo_app_service ◄─► demo_redis_service (own password, own volume)
                            demo_celery_worker (queue "demo")      │
                            demo_celery_beat (allowlisted schedule)│
                       └──► icd_api_service  (the ONE shared container, main's)
                       └──► PostgreSQL database minerva_demo (own role)
                       └──► S3 prefix demo/ (own IAM user)
```

## What is in the repository

| File | Purpose |
| --- | --- |
| `docker-compose.demo.yml` | A separate compose project `digitva-demo`: app, worker, beat, Redis, ingress |
| `.env.demo.example` | Template of the demo's env file (placeholders only) |
| `deploy/ingress-demo.conf` | nginx template of the demo ingress (client IP, 12 MB bodies, one upstream) |

**Why a separate project, not an overlay of `docker-compose.yml`.** An overlay
puts the demo's services in the main project, where `make prod`,
`make prod-down` and any `--remove-orphans` act on them; the demo's lifecycle
must not touch main's, and main's `.env` (its `SECRET_KEY`, blind-index key and
S3 credentials) must not interpolate into the demo. `extends:` would drag in
main's `container_name`, checkout bind mount, environment and secrets, each to
be unset by hand. A standalone file repeats a few lines and cannot leak.

**Same image, no duplicated pins.** The demo has no `build:`; it runs the image
main built (release pins for the Expo web export and smartva-rs are already in
it), tagged for the demo in step 2.

**No checkout mount.** The services run the image's own code. `config.py` calls
`load_dotenv()`, so a bind-mounted checkout would hand the demo (a public,
self-sign-up service) main's `.env`; `doris_public_service` already runs this
way. `docs/` is not in the image (`.dockerignore`), so help pages that read it
answer 404 on the demo.

Invocation, used throughout (always with `--env-file`; without it compose reads
the checkout's `.env`, which is main's, and the required `DEMO_*` variables
make `config` fail rather than start a half-main demo):

```bash
cd <checkout>
DD="docker compose --env-file /data/digitva-demo.env -f docker-compose.demo.yml"
```

## 1. Prerequisites

1. **Host headroom.** The demo's limits (below) add 2.3 GB of memory and
   2.75 CPU-cap. On the app host run `nproc`, `free -m` and
   `docker stats --no-stream`; main's limits are 1.5 + 1.5 + 0.4 + 0.1 GB, the
   ICD container 2 GB and DORIS 0.2 GB. If main's limits plus the demo's do not
   fit, lower the demo's in `docker-compose.demo.yml` first; do not start it
   and rely on the OOM killer.

   | Service | Memory | CPU cap | Why |
   | --- | --- | --- | --- |
   | `demo_app_service` | 768 MB | 1.0 (shares 256) | 1 gunicorn worker x 6 threads; the work is waiting (ICD, S3, database) |
   | `demo_celery_worker` | 1 GB | 1.0 (shares 256) | concurrency 1; SmartVA run plus audio conversion; main's is 1.5 GB |
   | `demo_celery_beat` | 320 MB | 0.25 | boots the whole app, no work of its own |
   | `demo_redis_service` | 160 MB | 0.25 | `--maxmemory 96mb`, headroom for the snapshot fork |
   | `demo_ingress` | 64 MB | 0.25 | nginx |

   `cpu_shares: 256` against the default 1024 means main wins when the host's
   CPUs are contended; the caps bound the demo when they are not.
2. **DNS.** `demo.causeofdeathindia.com` A record to the DMZ proxy's public IP.
   It must be a `*.causeofdeathindia.com` host: release builds of
   digitva-collect accept only those (`mobile/digitva-collect/src/enrolment.ts`).
3. **DMZ proxy** (do not enable the site yet, step 5): a certbot certificate
   for the host, and a server block like the main one:

   ```nginx
   server {
       listen 443 ssl;
       server_name demo.causeofdeathindia.com;
       # ssl_certificate / ssl_certificate_key: certbot, as for the main site
       client_max_body_size 12m;
       location / {
           proxy_pass https://<APP_PRIVATE_IP>:8001;
           proxy_ssl_name <BACKEND_TLS_NAME>;
           proxy_ssl_server_name on;
           proxy_ssl_trusted_certificate /etc/nginx/tls/<BACKEND_CA_FILE>;
           proxy_ssl_verify on;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

   `X-Forwarded-For $proxy_add_x_forwarded_for` is the line that matters, and
   the proxy must be the internet-facing edge (no CDN or load balancer in front
   of it; one in front adds a hop the app does not count). It must never pass
   the visitor's header on as it is (`$http_x_forwarded_for`, or none of the
   directive so the visitor's header is forwarded): the app trusts exactly the
   last entry, which this proxy appends. Security groups: the app host admits
   port 8001 from the proxy only, as for 8000.
4. **Why the ingress does not also append.** `ProxyFix(x_for=1)` in the app
   believes the last `X-Forwarded-For` entry and expects exactly one hop to have
   added it. The chain here is DMZ proxy, demo ingress, app. If the ingress used
   `$proxy_add_x_forwarded_for` too, the app would see the DMZ proxy's address
   for every visitor, and the per-IP sign-up limit (30 per hour) would lock the
   demo for everyone. So `deploy/ingress-demo.conf` takes the last entry from
   the DMZ proxy's address only (`DEMO_PROXY_FROM`, `set_real_ip_from`) and
   gives the app that one address. A request from any other peer keeps its own
   address, whatever header it sends; a wrong `DEMO_PROXY_FROM` makes everyone
   share the proxy's address (visible in step 9, and safe) rather than
   believing a header a visitor wrote.
5. **S3.** The bucket already exists for main. For the demo add a prefix `demo/`
   and a **separate IAM user** limited to it (the demo's credentials sit in a
   public service; they must not read main's attachments or dumps):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       { "Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
         "Resource": "arn:aws:s3:::DIGITVA_BUCKET/demo/*" },
       { "Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::DIGITVA_BUCKET",
         "Condition": { "StringLike": { "s3:prefix": ["demo/*"] } } }
     ]
   }
   ```

   Everything the app stores lands under `S3_PREFIX`: attachments, SmartVA run
   archives, exports and the nightly dump at
   `demo/db-backups/minerva_demo/pg_dump_minerva_demo_<UTC>.dump` (the dump's
   own folder is named after the database, so it cannot meet main's
   `db-backups/minerva/`). The lifecycle rule of [backup.md](backup.md) is scoped
   to `db-backups/` and does not match this prefix: add the same rule for the
   prefix `demo/db-backups/`. Bound: the limits allow 500 accounts x 10
   submissions x 6 files x 10 MB, 300 GB in the worst case; set a bucket-size
   alert for the prefix.
6. **Database.** On the database server (main's, or another), as an administrator:

   ```sql
   CREATE ROLE minerva_demo LOGIN PASSWORD '<strong, not main''s>';
   CREATE DATABASE minerva_demo OWNER minerva_demo;
   ```

   The role owns nothing in main's database and holds no privilege on its
   tables, so a connection there shows names at most. If you also want it
   refused at CONNECT, check `\l+ minerva` first: `REVOKE CONNECT ON DATABASE
   minerva FROM PUBLIC` is safe only when no other role relies on PUBLIC.

   Add `hostssl minerva_demo minerva_demo <APP_PRIVATE_IP>/32 scram-sha-256` to
   `pg_hba.conf` and reload. On the same server check `SHOW max_connections;`:
   the demo uses at most 8 (app) + 3 (worker) + 3 (beat) = 14, main 18, so the
   split production's 40 leaves 8 spare. A bundled server (`minerva_db_service`,
   `max_connections=40`, reached by its published address, as the demo is not
   on main's network) is the same arithmetic; raise it in `docker-compose.yml`
   before adding the demo if more headroom is needed.
   The database must be empty and hold only the demo project: the purge and
   the demo's startup work refuse a database with any other project, so a
   demo pointed at the main database by mistake does nothing.
7. **ICD container network.** The demo reaches `icd_api_service` over the
   external network `digitva_icd`, which `docker-compose.yml` creates and
   attaches only `icd_api_service` to (alias `icd_api_service`, in addition to
   main's default network). Only the demo's app and worker join it; the demo's
   beat, Redis and ingress do not, and the demo is never on main's default
   network, so it cannot reach main's Redis, database or app. Start main's
   ICD container (`docker compose --profile icd11 up -d icd_api_service`) once
   after pulling the compose change, so the network exists; check with
   `docker network inspect digitva_icd`. If you run the opt-in Rust ICD host
   (`icd_api_rust_service`) instead, it is not attached to `digitva_icd` yet:
   add it there first or the demo has no ICD service.
   A database on the same host is reached by its published address, not
   `minerva_db_service` (that name lives on main's network).

## 2. Image and secrets (once)

On the app host, as the deploy user:

```bash
# The demo runs the image main built. Record the tag you set.
docker tag "$(docker inspect -f '{{.Image}}' minerva_app)" digitva-demo-app:$(git rev-parse --short HEAD)

umask 077
install -m 600 .env.demo.example /data/digitva-demo.env       # then edit it
install -d -m 700 /data/digitva-secrets
```

Fill `/data/digitva-demo.env`. **Every secret is new**; none may equal a main
value. The file lives outside the checkout (the repository ignores `.env` and
`.env.demo` too). Generate the keys:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"   # DEMO_SECRET_KEY
openssl rand -hex 32                                         # DEMO_CAPTCHA_HMAC_KEY
openssl rand -base64 32 | tr '+/' '-_'                       # DEMO_AUTH_FACTOR_ENCRYPTION_KEY
openssl rand -hex 24                                         # DEMO_REDIS_PASSWORD
```

**Registration-number keys.** The demo registers deaths, and production refuses
to start without the key set, so it gets its own pair (never main's). The
private key is read by the app and worker only; beat gets none.

```bash
IMG=digitva-demo-app:$(git rev-parse --short HEAD)
docker run --rm --user "$(id -u):$(id -g)" -v /data/digitva-secrets:/pii-secret \
  --entrypoint python "$IMG" scripts/generate_pii_keys.py \
  --private-file /pii-secret/demo_pii_kem_private_key --env-file /pii-secret/demo_pii.env
sed 's/^PII_/DEMO_PII_/' /data/digitva-secrets/demo_pii.env >> /data/digitva-demo.env
shred -u /data/digitva-secrets/demo_pii.env 2>/dev/null || rm -f /data/digitva-secrets/demo_pii.env
```

Then set `DEMO_PII_KEM_PRIVATE_KEY_PATH=/data/digitva-secrets/demo_pii_kem_private_key`
(it is already the template's value). Back up the private key and the env file
apart from the database: a restored demo database is unreadable for
registration numbers without them (the demo holds no real data, so losing them
costs re-creating the accounts, not a case).

**Station signing key: not needed.** `BUNDLE_SERVER_SIGNING_KEY_FILE` is unset on
the demo. Issuing a station config answers 503 `station_config_unavailable` and
the app still starts; demo accounts cannot reach it.

## 3. First start

```bash
$DD config -q                          # no output = every required value is set
$DD up -d demo_redis_service demo_app_service
$DD logs -f demo_app_service           # boot.sh runs `flask db upgrade` on the new database
```

Wait until `$DD ps` shows `demo_app_service` healthy (a new database takes a
few minutes; the check allows 3). Then the rest, except the ingress:

```bash
$DD up -d demo_celery_worker demo_celery_beat
$DD logs --tail 30 demo_celery_worker demo_celery_beat
```

Check what runs and what does not:

```bash
$DD exec demo_app_service sh -c 'test ! -e /app/.env && test ! -e /app/private && echo "no checkout files"'
$DD exec demo_celery_beat sh -c 'ls /app/private /run/secrets 2>&1'          # empty / no such file
$DD exec demo_app_service python -c "from app import create_app; a=create_app(); print({k: v for k, v in a.config.items() if k.startswith('PUBLIC_DEMO') or k in ('CODING_SWEEP_INTERVAL_MINUTES', 'S3_PREFIX', 'ATTACHMENT_STORE')})"
```

The last line must show `PUBLIC_DEMO_ENABLED True`, `PUBLIC_DEMO_PURGE_ENABLED False`,
`CODING_SWEEP_INTERVAL_MINUTES 5`, `S3_PREFIX demo/` and the policy's limits.

## 4. Seed, admin, demo project

`flask seed run` creates the administrator `testadmin@digitva.com` with a
password that is written in this repository. **Replace it at once and before
the DMZ route exists (step 7)**; the demo is unreachable from the internet
until then.

```bash
$DD exec demo_app_service flask seed run
$DD exec demo_app_service flask users reset-password --email testadmin@digitva.com --onboarded
#   prints the new password once; store it in the password manager
$DD exec demo_app_service flask public-demo setup --by testadmin@digitva.com
```

`setup` is idempotent and prints JSON counts. Run no other project or
organization setup on this database (the purge and eviction require that the
demo project is the only one). Sign in as the administrator once from a
trusted network and enrol a second factor.

Check the schedule and the isolation:

```bash
# only the allowlisted tasks are enabled
$DD exec demo_app_service sh -c 'psql "$DATABASE_URL" -c "select task, enabled from celery_periodictask order by enabled desc, task"'

# the demo's Redis holds the demo's keys, the queue is "demo", main's Redis holds none
PW=$(grep '^DEMO_REDIS_PASSWORD=' /data/digitva-demo.env | cut -d= -f2-)
$DD exec demo_redis_service redis-cli --no-auth-warning -a "$PW" --scan | head
docker exec minerva_redis redis-cli --no-auth-warning -a "$MAIN_REDIS_PASSWORD" --scan --pattern 'demo*' | head   # nothing (read-only; main's password from its .env)
```

Enabled tasks: the SmartVA sweep, the stale-allocation and reviewer-eligible
sweep, the upload, notification, sign-in-IP and ICD search telemetry purges, the
daily demo purge and `run_db_backup`; nothing else (no ODK sync).

## 5. Ingress and the DMZ route

```bash
$DD up -d demo_ingress
$DD ps
curl -ks https://<DEMO_BIND_IP>:8001/health -H 'Host: localhost'   # on the app host
```

Then, on the DMZ proxy: enable the demo site, `sudo nginx -t && sudo systemctl reload nginx`.
`curl -sI https://digitvademo.causeofdeathindia.com/vaauth/signup` returns 200.

## 6. Verify

Do these with a throwaway account (usernames and data are visible to the demo
team; the 30-day rule applies). Each is a pass or fail.

1. **Sign-up.** `/vaauth/signup` shows the notice and the proof-of-work CAPTCHA; a
   12+ character password creates the account and signs in. The app's JSON
   sign-up works from digitva-collect ("Try the demo").
2. **Collect.** Start a verbal autopsy on the web: consent notice (English and
   Hindi), narration audio, an attachment. A 13 MB file is refused by the
   ingress (413); an 11 MB file is refused by the app (10 MB cap).
3. **SmartVA.** After submit, `/public-demo/cases` shows "waiting for SmartVA",
   then "ready to code" in a few minutes. `$DD logs demo_celery_worker` shows the
   task: the worker consumes only queue `demo`.
4. **Code.** The coding editor finds ICD-11 codes and DORIS runs, so the shared
   ICD container is reachable. Direct check:
   `$DD exec demo_app_service python -c "import os,urllib.request as u; print(u.urlopen(u.Request(os.environ['ICD11_API_BASE_URL']+'/icd/release/11/2026-01/mms', headers={'API-Version':'v2','Accept-Language':'en'}), timeout=10).status)"` prints 200.
5. **Review.** Five minutes after coding (recode window) plus the 5-minute
   sweep, the same account can review its own case.
6. **Report and download.** The report page shows the SmartVA cause, the coder's
   ICD-11 cause and the reviewer's verdict; CSV and JSON download work (10 per
   hour).
7. **Dashboard.** `/public-demo/dashboard`, signed out, shows totals and no
   rows or names.
8. **Isolation.** A second account cannot open the first account's case or
   attachment (404), and `/admin` and the people pages are refused.
9. **Client IP and the forged header.** From a machine whose public address you
   know (call it A):

   ```bash
   curl -s -o /dev/null -H 'X-Forwarded-For: 203.0.113.9' https://digitvademo.causeofdeathindia.com/vaauth/signup
   $DD logs --tail 3 demo_ingress
   ```

   The first field of the last log line must be **A**: not `203.0.113.9` (the
   proxy forwards the visitor's header unchecked: fix the proxy), and not the
   DMZ proxy's own address (`DEMO_PROXY_FROM` does not match the address the
   ingress sees: fix the value; until then every visitor shares one IP). Then
   confirm the app sees the same, after signing in as the throwaway account:

   ```bash
   $DD exec demo_app_service sh -c "psql \"\$DATABASE_URL\" -Atc \"select occurred_at, detail->>'ip' from auth_security_events where event_type='web_sign_in' order by occurred_at desc limit 3\""
   ```

   Also, from any host other than the DMZ proxy that can reach the port, the
   header must be ignored:
   `curl -ks -H 'X-Forwarded-For: 203.0.113.9' https://<APP_PRIVATE_IP>:8001/vaauth/signup`
   logs that host's own address.
10. **Limits.** Do not exhaust the sign-up limits (they are shared by everyone);
    the configured values printed in step 3 are the check, and
    `tests/test_public_demo.py` covers the behaviour.
11. **Bounds.** `docker stats --no-stream` shows the demo's memory limits
    (768 / 1024 / 320 / 160 / 64 MiB); `docker inspect -f '{{.HostConfig.NanoCpus}}' <container>`
    is non-zero for each. Main's `/health` and its containers are unaffected.

## 7. Backups, and only then the purge

The purge and the eviction at the 500-account cap delete accounts and everything
they created, so they stay off (`DEMO_PURGE_ENABLED=0`) until a nightly dump has
run and a restore from it has worked. While it is off, sign-up at the cap is
refused ("The demo is full") and no one is deleted.

1. **A dump now, and tomorrow's.** `run_db_backup` runs nightly at
   `DEMO_DB_BACKUP_TIME` (02:30 UTC, off main's 01:30). Take one on demand:

   ```bash
   $DD exec demo_app_service flask backups db-dump
   $DD exec demo_app_service flask backups db-list
   ```

   `status=success store=s3`, and the object is under
   `demo/db-backups/minerva_demo/` in the bucket (S3 console, or `aws s3 ls`
   as an administrator), not at the bucket root. After the first night,
   `db-list` shows the scheduled run. `store=local` means
   `DEMO_ATTACHMENT_STORE` is not `s3`: that dump lives on the host and does not
   meet the owner's backup requirement.
2. **Restore into a scratch database** (never over `minerva_demo`). As the
   database administrator: `CREATE DATABASE minerva_demo_restore OWNER minerva_demo;`
   then, with the key from `db-list` (store-relative, as printed):

   ```bash
   KEY=db-backups/minerva_demo/pg_dump_minerva_demo_<UTC>.dump
   $DD exec demo_app_service flask backups db-download "$KEY" /tmp/restore.dump
   $DD exec demo_app_service sh -c 'R=$(printf %s "$DATABASE_URL" | sed "s#@\(.*\)/minerva_demo#@\1/minerva_demo_restore#") &&
     pg_restore --no-owner --no-privileges -d "$R" /tmp/restore.dump &&
     psql "$R" -Atc "select version_num from alembic_version" &&
     psql "$R" -Atc "select count(*) from va_users" &&
     psql "$DATABASE_URL" -Atc "select count(*) from va_users"; rm -f /tmp/restore.dump'
   ```

   If the restore stops on `CREATE EXTENSION`, the role may not create
   extensions: run the `pg_restore` as the database administrator instead.
   The download verifies the recorded sha256. Both counts must agree (up to
   sign-ups since the dump) and the revision must equal
   `$DD exec demo_app_service flask db current`. Then `DROP DATABASE minerva_demo_restore;`.
3. **Dry-run the purge**, which deletes inside a transaction it rolls back:
   `$DD exec demo_app_service flask public-demo purge --dry-run`.
4. **Enable.** Set `DEMO_PURGE_ENABLED=1` in `/data/digitva-demo.env`, then
   `$DD up -d` (recreates the app, worker and beat, which read it). The daily
   purge task and the eviction now run; each writes one audit row of counts.

## 8. Operating

- **Logs.** `$DD logs -f demo_app_service` (also `/app/logs` in the `demo_logs`
  volume); container logs rotate at 3 x 10 MB.
- **Queue.** SmartVA runs one at a time; if the report sits on "waiting for
  SmartVA", watch it: `$DD exec demo_redis_service redis-cli --no-auth-warning -a "$PW" llen demo`.
  Raise `--concurrency` on the worker (and its memory limit) only if it stays
  long and the host has room.
- **Disk.** `docker system df -v | grep digitva-demo`: `demo_data` holds
  attachments only until the 10-minute sweep copies them to S3;
  `demo_smartva_runs` is archived and removed after each run.
- **Redis.** If the broker alone fills 96 MB, Redis refuses writes (`OOM`)
  instead of evicting queue data; raise `--maxmemory` and the limit together.
- **Stop.** Remove the DMZ site, then `$DD stop`. `$DD down` keeps the volumes;
  `$DD down -v` deletes the demo's local data and Redis volume (not the database
  or S3): do not run it without a reason.

## 9. Upgrade and rollback

The demo runs the same release as main.

1. Deploy main as usual (`make prod-build`).
2. Record the demo's current tag (`grep DEMO_APP_IMAGE /data/digitva-demo.env`)
   and take a dump: `$DD exec demo_app_service flask backups db-dump`.
3. Tag the new image: `docker tag "$(docker inspect -f '{{.Image}}' minerva_app)" digitva-demo-app:$(git rev-parse --short HEAD)`.
4. Set `DEMO_APP_IMAGE` to it and bump `DEMO_STATIC_ASSET_VERSION` in
   `/data/digitva-demo.env`.
5. `$DD up -d`. The app migrates the demo database on start (`boot.sh`), then the
   worker and beat follow; a new `.env` key listed in the release notes goes in
   the env file first. Re-run step 6 items 1, 3 and 9.

**Rollback.** Set `DEMO_APP_IMAGE` back to the recorded tag and `$DD up -d`. If
the new release ran a migration the old code cannot read, stop the services and
restore the pre-upgrade dump (as step 7.2, into `minerva_demo` with the
services stopped, after dropping and recreating it), then start the old tag.
Migrations are additive and reversible by policy, so a `flask db downgrade` is
the other path.

## 10. What the demo shares with main, and how it is bounded

| Shared | Bound |
| --- | --- |
| The WHO ICD-11/DORIS container | The demo-wide ICD limit (2000 per hour, 300 per account per hour; `PUBLIC_DEMO_ICD_*`) keeps demo users from starving main's coders; the container's own 2 GB limit |
| Host CPU and memory | Hard limits on every demo service (step 1), `cpu_shares 256` against main's default, log rotation |
| The database server (if main's) | A separate database and role; 14 connections at most; `idle_in_transaction_session_timeout` applies |
| The S3 bucket | A separate prefix and an IAM user that cannot read main's keys; per-account upload limits |
| A Docker network | Only `digitva_icd`, which holds `icd_api_service` and the demo's app and worker (step 1.7); the demo is not on main's default network |

Not shared: Redis (own password, own volume, own key prefix and Celery queue as
a second guard), the database, the secrets and keys, the volumes, the image
tag (set by the demo's env file), the ingress and its port.

## Needed outside the repository files this runbook ships

- `docker-compose.yml` (shipped): `icd_api_service` joins `digitva_icd`
  (step 1.7). If the demo shares the bundled database, raise
  `max_connections` there.
- The DMZ proxy: the server block of step 1.3, and its certificate.
