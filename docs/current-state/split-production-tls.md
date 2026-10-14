---
title: Split Production TLS
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-14
---

# Split Production TLS

Split production runs on three hosts in one VPC. Every hop is
encrypted and verified:

```
Browser ── HTTPS 443 ──► Proxy host (nginx) ── HTTPS 8000 ──► App host ── TLS 5432 ──► DB host
          Let's Encrypt              verified as <BACKEND_TLS_NAME>   sslmode=verify-full on <DB_PRIVATE_IP>
```

Deployment specifics (addresses, names, key strength, validity) are
placeholders. Substitute them wherever they appear below:

| Placeholder | Meaning |
| --- | --- |
| `<PUBLIC_HOSTNAME>` | Public DNS name browsers use; its A record points at `<PROXY_PUBLIC_IP>` |
| `<PROXY_PUBLIC_IP>` / `<PROXY_PRIVATE_IP>` | Proxy host's public (Elastic) IP and VPC address |
| `<APP_PRIVATE_IP>` | App host's VPC address: `APP_BIND_IP` in `.env`, nginx `proxy_pass`, `pg_hba` source, app certificate SAN |
| `<DB_PRIVATE_IP>` | DB host's VPC address: `DATABASE_URL` host, `listen_addresses`, database certificate SAN |
| `<BACKEND_TLS_NAME>` | Name in the app certificate that nginx checks (`proxy_ssl_name`); a private name such as `app-backend.internal` |
| `<BACKEND_CA_FILE>` | File name on the proxy host holding the app's public certificate |
| `<SITE_NAME>` | nginx `sites-enabled` link name |
| `<DB_TLS_CN>` | Common name in the database certificate (verification uses the IP SAN, not this) |
| `<DB_USER>` | PostgreSQL login role for the app: non-superuser, owner of database `minerva` |
| `<KEY_ALG>` | `openssl -newkey` argument, for example `rsa:3072` (the script's default) or `ec -pkeyopt ec_paramgen_curve:P-256` |
| `<DAYS>` | Certificate validity in days |

| Host | Private IP | Role |
| --- | --- | --- |
| Proxy host | <PROXY_PRIVATE_IP> (Elastic IP <PROXY_PUBLIC_IP>) | Public nginx for `<PUBLIC_HOSTNAME>` |
| App host | <APP_PRIVATE_IP> | App, Celery worker and beat, Redis (Compose, `make prod`) |
| DB host | <DB_PRIVATE_IP> | Native PostgreSQL 18, systemd unit `postgresql@18-main` |

The app and database hosts are administered through SSM; SSH is closed. Security groups
admit port 8000 on the app only from the proxy host, and port 5432 on the database
only from the app.

Each private key stays on the host that serves it. Each client holds only the
public certificate it trusts. Both private certificates are self-signed, so
the `ca.crt` the client trusts is a copy of the server's `server.crt`.

## Where every file lives

| Host | Path | Mode | Contents | Read by |
| --- | --- | --- | --- | --- |
| Proxy host | `/etc/letsencrypt/live/<PUBLIC_HOSTNAME>/{fullchain,privkey}.pem` | certbot | Public certificate for browsers | nginx `listen 443` |
| Proxy host | `/etc/nginx/tls/<BACKEND_CA_FILE>` | 0644 | Copy of the app's `server.crt` | nginx `proxy_ssl_trusted_certificate` |
| Proxy host | `/etc/nginx/sites-available/<PUBLIC_HOSTNAME>.conf` | 0644 | Site config, enabled as `sites-enabled/<SITE_NAME>` | nginx |
| App host | `/etc/digitva-app/tls/server.key` | 0600 | Backend private key | `digitva_ingress` nginx `ssl_certificate_key` |
| App host | `/etc/digitva-app/tls/server.crt`, `ca.crt` | 0644 | App certificate (CN and SAN `<BACKEND_TLS_NAME>`, `localhost`, `<APP_PRIVATE_IP>`) | `digitva_ingress` nginx `ssl_certificate`; the app reads `server.crt` for System health; `ca.crt` is the copy given to the proxy host |
| App host | `/etc/digitva-db/ca.crt` | 0644 | Copy of the database's `server.crt` | `sslrootcert` in `DATABASE_URL` |
| App host | `/data/digitva-db.env` | 0600 | `DATABASE_URL=postgresql://<DB_USER>:<password>@<DB_PRIVATE_IP>:5432/minerva?sslmode=verify-full&sslrootcert=/etc/digitva-db/ca.crt` | Compose interpolation |
| DB host | `/etc/postgresql/18/main/tls/server.{crt,key}` | 0644 / 0600, owner `postgres` | Database certificate (CN `<DB_TLS_CN>`, SAN `IP:<DB_PRIVATE_IP>`) | PostgreSQL |
| DB host | `/var/lib/digitva-db/admin/application-password` | 0600 root, directory 0700 | `<DB_USER>` password | Administrators only |

None of these files is in the repository. The repository only names their
paths, in
[`docker-compose.external-db.yml`](../../docker-compose.external-db.yml):

- `/etc/digitva-db/ca.crt` is mounted read-only into the app, worker, beat and
  DORIS containers.
- `/etc/digitva-app/tls/server.crt` alone (never the key) is mounted read-only
  into the Celery worker, where the daily TLS health check reads its expiry.
  It is a single-file bind mount: renew it by copying over it in place.
- `/etc/digitva-app/tls` (certificate and key) is mounted read-only into the
  `digitva_ingress` nginx container only. It serves HTTPS on container port
  443, published at `${APP_BIND_IP}:8000`
  ([`deploy/doris-public-nginx-tls.conf`](../../deploy/doris-public-nginx-tls.conf)),
  and routes `/help/doris-demo` and `/api/v1/doris-demo/` to the public DORIS
  demo and everything else to the clinical app over plain HTTP inside Docker
  (shared rules in `deploy/ingress-routes.conf`). The app container gets
  `server.crt` alone, for the System health panel; gunicorn speaks plain HTTP.
  `.env` on the app VM sets `APP_BIND_IP=<APP_PRIVATE_IP>` and
  `PUBLIC_BASE_URL=https://<PUBLIC_HOSTNAME>`; the app answers only that `Host`
  and `localhost` (see [Installation](installation.md#production-notes)).
- The public DORIS demo, its ingress and the WHO ICD-11 API always start on
  this host (their `icd11` compose profile is reset in the overlay), and the
  demo's session cookie is `Secure`.

`make prod` picks up the overlay on its own on the app VM, because
`/data/digitva-db.env` exists there.

## Setup

Run as root (`sudo -i`) on the host named in each heading.

### App VM: backend certificate

```bash
umask 077
TLS=/etc/digitva-app/tls
install -d -m 0755 "$TLS"
openssl req -x509 -newkey <KEY_ALG> -nodes -days <DAYS> \
  -subj /CN=<BACKEND_TLS_NAME> \
  -addext 'subjectAltName=DNS:<BACKEND_TLS_NAME>,DNS:localhost,IP:<APP_PRIVATE_IP>' \
  -addext 'extendedKeyUsage=serverAuth' \
  -keyout "$TLS/server.key" -out "$TLS/server.crt"
chmod 0600 "$TLS/server.key"; chmod 0644 "$TLS/server.crt"
cp "$TLS/server.crt" "$TLS/ca.crt"; chmod 0644 "$TLS/ca.crt"
openssl verify -CAfile "$TLS/ca.crt" -verify_hostname <BACKEND_TLS_NAME> "$TLS/server.crt"
```

Copy `ca.crt` to the proxy host as `/etc/nginx/tls/<BACKEND_CA_FILE>` (see
[Copying a public certificate](#copying-a-public-certificate)).

### Database VM: PostgreSQL 18 from PGDG

Install PostgreSQL from the signed PGDG repository (`/etc/apt/sources.list.d/digitva-pgdg.sources`, the
`<ubuntu-codename>-pgdg` suite for the host's architecture, key
`/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc`). Before installing
`postgresql-18`, disable automatic cluster creation on the OS disk
(`create_main_cluster = false` in `/etc/postgresql-common/createcluster.conf`).
Then create the cluster on the encrypted volume mounted at `/data`:

```bash
install -d -m 0700 -o postgres -g postgres /data/postgresql /data/postgresql/18
pg_createcluster 18 main --datadir=/data/postgresql/18/main \
  -- --data-checksums --auth-local=peer --auth-host=scram-sha-256
```

### Database VM: certificate

```bash
CONFIG=/etc/postgresql/18/main
install -d -m 0755 -o postgres -g postgres "$CONFIG/tls"
openssl req -x509 -newkey <KEY_ALG> -nodes -days <DAYS> \
  -subj /CN=<DB_TLS_CN> -addext 'subjectAltName=IP:<DB_PRIVATE_IP>' \
  -keyout "$CONFIG/tls/server.key" -out "$CONFIG/tls/server.crt"
chown postgres:postgres "$CONFIG/tls/server.key" "$CONFIG/tls/server.crt"
chmod 0600 "$CONFIG/tls/server.key"; chmod 0644 "$CONFIG/tls/server.crt"
```

Copy `server.crt` to the app host as `/etc/digitva-db/ca.crt`.

### Database VM: network, TLS and authentication

`/etc/postgresql/18/main/conf.d/digitva.conf`:

```
listen_addresses = '<DB_PRIVATE_IP>'
port = 5432
ssl = on
ssl_min_protocol_version = 'TLSv1.2'
ssl_cert_file = '/etc/postgresql/18/main/tls/server.crt'
ssl_key_file = '/etc/postgresql/18/main/tls/server.key'
password_encryption = 'scram-sha-256'
shared_buffers = '128MB'
effective_cache_size = '512MB'
max_connections = 40
work_mem = '4MB'
max_wal_size = '256MB'
min_wal_size = '80MB'
```

`max_connections = 40` matches the pool budget in `config.py`:
3 processes × (3 + 5 overflow) = 24, plus margin for administration.

Optionally, `/etc/postgresql/18/main/conf.d/digitva-monitoring.conf` sets
`shared_preload_libraries = 'pg_stat_statements'`, with the extension owned by
`postgres`. Every application object is owned by `<DB_USER>`.

`/etc/postgresql/18/main/pg_hba.conf`:

```
local all postgres peer
local all all peer
hostssl minerva <DB_USER> <APP_PRIVATE_IP>/32 scram-sha-256
host all all 0.0.0.0/0 reject
host all all ::/0 reject
host replication all 0.0.0.0/0 reject
host replication all ::/0 reject
```

`/etc/systemd/system/postgresql@18-main.service.d/digitva-data.conf` stops
PostgreSQL from starting without the data volume:

```
[Unit]
RequiresMountsFor=/data

[Service]
ExecStartPre=/usr/bin/mountpoint -q /data
Restart=on-failure
RestartSec=5s
```

### Database VM: role and database

Create `<DB_USER>` as `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
NOBYPASSRLS`, owning database `minerva`, with `CONNECT` revoked from `PUBLIC`.
Generate the password with `openssl rand -hex 32` and pass it to `psql` over
stdin with statement logging off for that session, so it never reaches a log
or the shell history. Store it only in
`/var/lib/digitva-db/admin/application-password` and in the app host's
`/data/digitva-db.env`.

### Proxy host: public certificate and site

Issue the Let's Encrypt certificate with certbot `--webroot
/var/www/letsencrypt` and `--deploy-hook 'nginx -t && systemctl reload
nginx'`, then confirm `certbot renew --dry-run`. The site:

- **Port 80:** serves `/.well-known/acme-challenge/` from `/var/www/letsencrypt`
  and redirects everything else to HTTPS.
- **Port 443:** uses the Let's Encrypt certificate, with `client_max_body_size
  55m` (above the 50 MB attachment cap; at 20m nginx would refuse a 20-50 MB
  upload with its own 413 before the app sees it), and passes requests on with these settings:

```
proxy_pass https://<APP_PRIVATE_IP>:8000;
proxy_ssl_server_name on;
proxy_ssl_name <BACKEND_TLS_NAME>;
proxy_ssl_verify on;
proxy_ssl_trusted_certificate /etc/nginx/tls/<BACKEND_CA_FILE>;
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;
proxy_connect_timeout 5s;
proxy_read_timeout 180s;
proxy_send_timeout 180s;
```

The app's `ProxyFix(x_for=1, x_proto=1, x_host=1)` trusts exactly this one
hop.

## Verifying

On the proxy host, with the app running:

```bash
openssl s_client -connect <APP_PRIVATE_IP>:8000 -servername <BACKEND_TLS_NAME> -verify_hostname <BACKEND_TLS_NAME> -CAfile /etc/nginx/tls/<BACKEND_CA_FILE> -brief </dev/null
```

Expect `Verification: OK`.

On the app VM, test the database hop with the URL and certificate the app
itself uses:

```bash
sudo docker exec minerva_app sh -c 'psql "$DATABASE_URL" -Atc "select ssl, version from pg_stat_ssl where pid = pg_backend_pid()"'
```

Expect `t|TLSv1.3`.

## Monitoring

The admin **System health** panel shows the live expiry of the app HTTPS
certificate, the PostgreSQL certificate as presented, each certificate in the
database trust bundle, and the public certificate. The admin index shows a
banner when one is due or urgent. The same panel also probes the S3 attachment
store (credentials and bucket access, a write/delete probe, and that objects
are reachable only through presigned links, never publicly; probes under
`<S3_PREFIX>health/`). A daily Celery beat task (`TLS_HEALTH_DAILY_TIME`) emails
admins while any of that holds. Thresholds, who is notified, the IAM actions the
probe needs and what is never shown are in
`docs/policy/tls-certificate-monitoring.md`.

## Renewal

Let's Encrypt renewal is automated by certbot. The app and database
certificates are self-signed and rotated by hand. Rotate them about 30 days
before expiry, or at once if a private key may have been exposed.

[`scripts/make-tls-cert.sh`](../../scripts/make-tls-cert.sh) reissues a
private certificate the same way as [Setup](#setup), with `KEY_ALG` and `[days]`
set to the chosen `<KEY_ALG>` and `<DAYS>`. It writes `server.key`,
`server.crt` and `ca.crt` into a new directory and refuses to overwrite an
existing key. Run it on the host that serves the certificate. On a host without
the repository, paste the script over SSM first.

A self-signed certificate is its own trust anchor, so the order matters:

1. Distribute a trust bundle holding both the old and the new public
   certificate. nginx and libpq both accept a file with several certificates.
2. Replace the server certificate and key.
3. Reload PostgreSQL, or recreate the app container.
4. Verify the connection (see [Verifying](#verifying)).
5. Only then remove the old certificate from the trust bundle.

**App certificate.** On the app VM:

```bash
scripts/make-tls-cert.sh /etc/digitva-app/tls.new <BACKEND_TLS_NAME> \
  DNS:<BACKEND_TLS_NAME>,DNS:localhost,IP:<APP_PRIVATE_IP>
```

1. On the proxy host, append the new `ca.crt` to
   `/etc/nginx/tls/<BACKEND_CA_FILE>`, then run
   `nginx -t && systemctl reload nginx`.
2. On the app VM, copy the new files over the old ones in place:
   `cp /etc/digitva-app/tls.new/* /etc/digitva-app/tls/`. Moving directories
   instead would leave the container bound to the old directory.
3. Reload the ingress, which reads the certificate at startup or reload:
   `docker compose --env-file .env --env-file /data/digitva-db.env -f docker-compose.yml -f docker-compose.external-db.yml exec digitva_ingress nginx -s reload`.
4. Verify from the proxy host with `openssl s_client`, then remove the old
   certificate from the proxy host's file and reload nginx.

**Database certificate.** On the database VM:

```bash
scripts/make-tls-cert.sh /etc/postgresql/18/main/tls.new <DB_TLS_CN> IP:<DB_PRIVATE_IP>
chown -R postgres:postgres /etc/postgresql/18/main/tls.new
```

1. On the app VM, append the new `ca.crt` to `/etc/digitva-db/ca.crt`. The file
   is bind-mounted, so the next new connection reads it.
2. On the database VM, run
   `cp -p /etc/postgresql/18/main/tls.new/server.* /etc/postgresql/18/main/tls/`,
   then `systemctl reload postgresql@18-main`. A reload picks up the new
   certificate.
3. Verify from the app container with `psql "$DATABASE_URL"`, then remove the
   old certificate from `/etc/digitva-db/ca.crt`.

`/etc/digitva-db/ca.crt` is a single-file bind mount. Edit it in place with
`tee`/`tee -a`; an editor that writes a new file would hide the change from
running containers until they restart.

### Copying a public certificate

Copy public certificates as plain text over SSM. Run `cat` on the source, and
paste into `tee` (or `tee -a` to append) on the destination. Never copy a
`server.key`.
