---
title: Split Production Deploy Runbook
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-25
---

# Split Production Deploy Runbook

How to deploy a new version to the disaggregated (split) production: a reverse
proxy host, an app host running Docker Compose, and a database host running
native PostgreSQL. Run each step by hand over SSM. Placeholders and file
locations are as in [Split Production TLS](split-production-tls.md); this
runbook does not repeat the one-time setup described there.

For Digitvav3 staging, use the repository's `scripts/deploy-staging.sh <full-git-sha>`
from the Mac after the `Server images` workflow passes. It connects through SSM
to `i-0b2caee6465bfcac1` (`digitva` profile, `ap-south-1`), verifies a database
backup before deployment, preserves the hosted Android APK override, and prints
the previous image's rollback command. The shared server-side procedure remains
`scripts/deploy-server.sh`; neither script builds on the server.
The shared SSM command helper is `scripts/ssm.sh`; load-test scripts use the
same helper.

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

`make prod`, `make prod-pull` and `make prod-down` use this command on this
host (they add the external-db overlay because `/data/digitva-db.env` exists)
plus `docker-compose.images.yml`, so `$DC` for `ps`, `exec` and `logs` below
also needs `-f docker-compose.images.yml` appended. **Nothing is built on the
host** ([policy](../policy/server-builds.md)): the app, worker, beat and DORIS
services run `ghcr.io/drguptavivek/digitva-app:<git sha>`, built by the
`Server images` GitHub workflow (native arm64 runner) from the commit being
deployed. Before a deploy, run that workflow for the release commit
(Actions, Server images, ref = the commit or `main`) and note the full sha.

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
`make prod-pull`, or `make ensure-secrets-prod` stops the deploy:
`sudo install -d -m 700 -o <deploy user> /data/digitva-secrets && mv
private/pii_kem_private_key /data/digitva-secrets/ && chmod 600
/data/digitva-secrets/pii_kem_private_key` (back it up apart first). Beat then
starts with `private/` masked; DORIS runs the image's code (a new image on
every deploy).

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

New `.env` keys from the release notes go in first (and bump
`STATIC_ASSET_VERSION`). Then one command, which repeats step 3's verified
backup, checks out the sha, pins it and pulls:

```bash
scripts/deploy-server.sh <full git sha of the Server images build>
```

It refuses a sha whose image is not in GHCR (`docker manifest inspect`),
stops if the dump is not a success or the checkout has local changes, runs
`git checkout --detach <sha>` (the checkout is bind-mounted into the app,
worker and beat, so code and image must be the same commit), updates the
submodule, writes `DIGITVA_IMAGE_TAG=<sha>` to `.env`, runs `make prod-pull`
(`compose pull` and `up -d --no-build`; no builder, no build cache), waits for
`minerva_app` to be healthy, checks `flask db current` equals `flask db heads`,
prints disk use, and removes images other than this sha and the previous one.
The app container runs `flask db upgrade` before gunicorn starts; the worker
and beat wait for the app to be healthy. First deploy on a host: do the
one-time GHCR login in "Registry access" below; the script sets
`DIGITVA_IMAGE_TAG`.

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

If the post-checks fail and the cause is not obvious within minutes, redeploy
the previous sha (the script prints it on failure; it is also the old
`DIGITVA_IMAGE_TAG`, kept on the host with its image):

```bash
make prod-rollback TAG=<previous full sha>
```

This is the same script without a new backup (`SKIP_BACKUP=1`): detached
checkout of that commit, pin, pull, start. Never `make prod-build`.

Migrations are additive, so the previous code runs against the newer schema;
do not run `flask db downgrade` unless the release notes say a migration must
be reversed. If data was damaged, restore the step 3 dump on the database host
(`flask backups db-download <object key> <path>` on the app host, copy it
over, then `pg_restore --no-owner --no-privileges` into a fresh database and
switch `DATABASE_URL`), never over the live database.

The checkout stays detached at the deployed sha; each deploy names its sha, so
no `git checkout main` is needed.

## Registry access (one-time, owner)

Images are pulled from GHCR, so the host must be able to read the package
`digitva-app`. Options:

| Option | Trade-off |
| --- | --- |
| Read-only token (recommended): a classic PAT with only `read:packages` (fine-grained tokens cannot read GHCR packages), `echo $TOKEN \| docker login ghcr.io -u <user> --password-stdin` on each host | Packages stay private; a leaked token reads images only. Tied to a person; rotate yearly. Stored in `~/.docker/config.json`, mode 0600. |
| Public package (Package settings, change visibility) | No credentials on hosts. Safe only because the repository is public and `.dockerignore` keeps `.env` and `private/` out; anyone can pull. |
| `GITHUB_TOKEN` from CI | Not usable on servers (expires with the job). |

The first `Server images` run creates the package private and links it to the
repository (`org.opencontainers.image.source`). Create the GitHub environment
`server-images` (Settings, Environments) with required reviewers and the
allowed branch (`main`) and tag (`server-v*`) before the first run.

## Notes

- `.env` on each host carries `DIGITVA_IMAGE_TAG=<sha>` (written by the
  script; optional `DIGITVA_IMAGE_REGISTRY`, default `ghcr.io/drguptavivek`).
  The repo pins no sha.

- One deploy at a time; nobody runs `docker compose` on the app host with a
  different file set during a deploy (a bare `docker compose up` would start
  the dev override).
- Certificate renewal is its own procedure: [Split Production TLS](split-production-tls.md#renewal).
- Proxy changes (for example `client_max_body_size`) are applied on the proxy
  host with `sudo nginx -t && sudo systemctl reload nginx`, before the app
  deploy that needs them.
