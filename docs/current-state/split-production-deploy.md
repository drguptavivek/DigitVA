---
title: Split Production Deploy Runbook
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-23
---

# Split Production Deploy Runbook

How to deploy a new version to the disaggregated (split) production: a reverse
proxy host, an app host running Docker Compose, and a database host running
native PostgreSQL. Run each step by hand over SSM. Placeholders and file
locations are as in [Split Production TLS](split-production-tls.md); this
runbook does not repeat the one-time setup described there.

```
Proxy host (nginx, public TLS) ──HTTPS :8000──► App host (ingress, app, Celery, Redis, WHO ICD-11 API, DORIS demo)
                                                       └──TLS :5432──► DB host (PostgreSQL 18)
```

Only the app host changes in a normal deploy. The proxy and database hosts
are checked, not changed.

## 0. Before you start

- Read the release's commit message and `handoff.md` "deploy notes" for new
  `.env` keys, migrations, or proxy changes.
- Pick a quiet time: a deploy restarts the app, worker and beat (about a
  minute of 502s through the proxy).
- On the app host, work as the user that owns the checkout, in the repo
  directory, and define the compose command once per session:

```bash
DC="docker compose --env-file .env --env-file /data/digitva-db.env -f docker-compose.yml -f docker-compose.external-db.yml"
```

`make prod`, `make prod-build` and `make prod-down` use exactly this command on
this host (they add the overlay because `/data/digitva-db.env` exists).

## 1. Checks on the proxy and database hosts (no changes)

Proxy host:

- `sudo nginx -T | grep -E "client_max_body_size|proxy_pass|proxy_ssl_name|proxy_ssl_verify"`
  shows `client_max_body_size 55m` (or more), `proxy_pass https://<APP_PRIVATE_IP>:8000`,
  `proxy_ssl_name <BACKEND_TLS_NAME>`, `proxy_ssl_verify on`.
- The case list CSV export (`GET /api/v1/cases/export.csv`) streams registration
  numbers in plaintext. A proxy location for it must not buffer or spool to disk:
  `proxy_buffering off;` and `proxy_max_temp_file_size 0;` (the app also sends
  `X-Accel-Buffering: no`, which nginx honours, but the directives do not depend
  on the header). `deploy/ingress-routes.conf` already has them for the ingress.
  Check with `sudo nginx -T | grep -E "proxy_buffering|proxy_max_temp_file_size"`.
- `sudo certbot certificates` shows the public certificate valid.

Database host:

- `systemctl is-active postgresql@18-main` prints `active`.
- `sudo -u postgres psql -Atc "show max_connections"` is at least 40 (the
  app host uses at most 18).
- `df -h /data` has room for the migration and a day of WAL.

## 2. Preflight on the app host (no changes)

Record what is running now, for rollback:

```bash
git rev-parse HEAD | tee ~/deploy-previous-commit
$DC images | tee ~/deploy-previous-images
```

Configuration:

```bash
stat -c '%a %n' /data/digitva-db.env                     # 600
grep -E '^FLASK_(ENV|DEBUG)=' .env                        # prints nothing
for k in PUBLIC_BASE_URL APP_BIND_IP STATIC_ASSET_VERSION ATTACHMENT_STORE S3_SERVER S3_BUCKET S3_PREFIX S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY SECRET_KEY CAPTCHA_HMAC_KEY AUTH_FACTOR_ENCRYPTION_KEY PII_KEM_PUBLIC_KEY PII_KEM_KEY_ID PII_BLIND_INDEX_KEY; do
  grep -q "^$k=." .env && echo "ok   $k" || echo "MISSING $k"
done
grep -q '^MAIL_BASE_URL=' .env && echo "rename MAIL_BASE_URL to PUBLIC_BASE_URL"
# PII KEM private key: outside the checkout, deploy user, 0600 (`make prod*`
# refuse otherwise; the checkout is bind-mounted into every app container).
key=$(sed -n 's/^PII_KEM_PRIVATE_KEY_PATH=//p' .env | tail -n1); key=${key:-/data/digitva-secrets/pii_kem_private_key}
stat -c '%a %U %n' "$key"                                  # 600 <deploy user>
case "$key" in "$PWD"/*|/*/../*|[!/]*) echo "MOVE the key outside the checkout";; esac
test ! -e private/pii_kem_private_key || echo "MOVE private/pii_kem_private_key to $key and delete the copy"
```

**First deploy after the key move (2026-10-21 fix batch).** Hosts that kept
the key at the old default `./private/pii_kem_private_key` must move it before
`make prod-build`, or `make ensure-secrets-prod` stops the deploy:
`sudo install -d -m 700 -o <deploy user> /data/digitva-secrets && mv
private/pii_kem_private_key /data/digitva-secrets/ && chmod 600
/data/digitva-secrets/pii_kem_private_key` (back it up apart first). Beat then
starts with `private/` masked; DORIS runs the image's code (rebuilt by
`make prod-build`).

Certificates (expiry dates; renew first if either is within 30 days):

```bash
sudo openssl x509 -in /etc/digitva-app/tls/server.crt -noout -enddate -ext subjectAltName
sudo openssl x509 -in /etc/digitva-db/ca.crt -noout -enddate
```

Database reachable over verified TLS from a throwaway container, before
anything is stopped:

```bash
$DC run --rm --no-deps --entrypoint sh minerva_app_service -c \
  'psql "$DATABASE_URL" -Atc "select current_user, version()"'
```

Stop here if any check fails.

## 3. Back up

A verified dump to the bucket (`<S3_PREFIX>db-backups/<db>/`), without
pruning older dumps:

```bash
$DC exec minerva_app_service flask backups db-dump --no-prune
$DC exec minerva_app_service flask backups db-list --limit 3
```

The newest line must say success. Note its object key for rollback. The
database volume's EBS snapshot is an independent second copy.

## 4. Deploy

```bash
git fetch origin && git status -sb          # no local changes
git pull --ff-only
git submodule sync vendor/smartva-analyze           # remote URL from .gitmodules
git submodule update --init vendor/smartva-analyze   # pull does not move it
# New .env keys from the release notes go in now (and bump STATIC_ASSET_VERSION).
make prod-build
```

`git pull` leaves submodule checkouts where they were, so without the
submodule update `git status` shows ` M vendor/smartva-analyze` and the image's
Python SmartVA path dependency is built from the old checkout. `git submodule
sync` first: an old checkout's `.git/config` can still point at upstream
`ihmeuw/SmartVA-Analyze`, which lacks commits that exist only on the
`drguptavivek` fork named in `.gitmodules` (staging, 2026-10-23). The smartva-rs
engine itself comes from the pinned release tarball, not from this checkout.

`make prod-build` builds the images and recreates the changed containers. The
app container runs `flask db upgrade` before gunicorn starts; the worker and
beat wait for the app to be healthy.

Watch it come up:

```bash
$DC ps
$DC logs -f --since 5m minerva_app_service     # until gunicorn reports "Booting worker"
```

## 5. Post-checks

```bash
$DC exec minerva_app_service flask db heads      # one head
$DC exec minerva_app_service flask db current    # equals the head
$DC ps --format '{{.Name}} {{.Status}}'          # all Up; app (healthy)
```

The backend TLS through the ingress, verified as the proxy verifies it:

```bash
curl -fsS --cacert /etc/digitva-app/tls/ca.crt \
  --resolve <BACKEND_TLS_NAME>:8000:<APP_PRIVATE_IP> \
  https://<BACKEND_TLS_NAME>:8000/health && echo " backend ok"
curl -fsS -o /dev/null -w '%{http_code}\n' --cacert /etc/digitva-app/tls/ca.crt \
  --resolve <BACKEND_TLS_NAME>:8000:<APP_PRIVATE_IP> \
  https://<BACKEND_TLS_NAME>:8000/help/doris-demo           # 200
```

Through the public hostname, from any browser:

1. `https://<PUBLIC_HOSTNAME>/help/doris-demo` loads while logged out.
2. Sign in as an admin; **Admin → System health**: every certificate row OK,
   S3 access, write/delete and "public access blocked" OK.
3. Open one case on the coding screen and one attachment (signed S3 link).

## 6. Rollback

If the post-checks fail and the cause is not obvious within minutes:

```bash
git checkout "$(cat ~/deploy-previous-commit)"
git submodule sync vendor/smartva-analyze
git submodule update --init vendor/smartva-analyze
make prod-build
```

Migrations are additive, so the previous code runs against the newer schema;
do not run `flask db downgrade` unless the release notes say a migration must
be reversed. If data was damaged, restore the step 3 dump on the database host
(`flask backups db-download <object key> <path>` on the app host, copy it
over, then `pg_restore --no-owner --no-privileges` into a fresh database and
switch `DATABASE_URL`), never over the live database.

Return to `main` afterwards with `git checkout main` once the fix is released.

## Notes

- One deploy at a time; nobody runs `docker compose` on the app host with a
  different file set during a deploy (a bare `docker compose up` would start
  the dev override).
- Certificate renewal is its own procedure: [Split Production TLS](split-production-tls.md#renewal).
- Proxy changes (for example `client_max_body_size`) are applied on the proxy
  host with `sudo nginx -t && sudo systemctl reload nginx`, before the app
  deploy that needs them.
