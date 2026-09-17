---
title: Backup And Restore
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-17
---

# Backup And Restore

## Summary

The VM is small and its disk is the scarce resource, so DigitVA keeps no dump
history on it. Postgres itself stays on the VM; its dumps do not.

With `ATTACHMENT_STORE=s3` a nightly `pg_dump -Fc` is streamed to one temporary
file, uploaded to the DigitVA bucket under
`db-backups/{db_name}/pg_dump_{db_name}_{UTC timestamp}.dump`, verified, and the
temporary file is removed. Retention is a count of dumps
(`DB_BACKUP_KEEP_DAILY`, default 30) applied to the objects in that prefix. The
only history left on the VM is the `va_db_backups` table.

On the local store the same dump lands in `DB_BACKUP_LOCAL_DIR` and is pruned
there the same way, so the commands remain useful in development.

A dump is the whole database — every payload, every narrative, every ODK
credential ciphertext. It is PHI and more. A backup object is **never presigned
and never served to a browser**; the only way back to one is an operator with
bucket credentials.

Implementation:

- [`app/services/db_backup_service.py`](../../app/services/db_backup_service.py) — the dump, the upload, retention, and the verified download
- [`app/tasks/backup_tasks.py`](../../app/tasks/backup_tasks.py) — the `run_db_backup` task and the beat entry
- [`app/commands/backups.py`](../../app/commands/backups.py) — `flask backups …`
- [`app/models/va_db_backups.py`](../../app/models/va_db_backups.py) — the history table
- migration `b7c41e0d95af`

## Schedule

The beat schedule lives in the database (`sqlalchemy_celery_beat`), like every
other DigitVA schedule. `ensure_db_backup_scheduled()` seeds it idempotently on
worker startup from [`make_celery.py`](../../make_celery.py):

| Beat row | Task | When |
|---|---|---|
| `Database backup — daily` | `app.tasks.backup_tasks.run_db_backup` | `DB_BACKUP_DAILY_TIME` (default `01:30`) UTC, via a `celery_crontabschedule` row |

Changing `DB_BACKUP_DAILY_TIME` and restarting `minerva_celery_beat` repoints
the existing row at the new crontab rather than creating a second schedule. An
unparseable value is logged and falls back to `01:30` — a misconfigured time
never stops the database being backed up.

The task creates the dump and then prunes. It never raises: a failure is a
`va_db_backups` row with `status='failed'` and a short `error_code`, which is
what the admin panel shows. The prune is skipped when the dump failed, so a bad
night can never also delete the last good dump.

## Retention

`DB_BACKUP_KEEP_DAILY` (default 30) is a count, not a number of days. Dumps are
ordered newest-first by the UTC timestamp in their own file name — not by the
object's `LastModified`, so a clock skew cannot reorder history — and everything
past the first N is deleted. The value is clamped to at least 1, so
`DB_BACKUP_KEEP_DAILY=0` is a no-op rather than a wipe. A listing that fails
skips the prune entirely; nothing is deleted on a partial view of the store.

### Bucket lifecycle rule (recommended)

The DigitVA bucket has versioning on. Deleting a pruned dump therefore leaves a
**noncurrent version** of it, which keeps paying for storage forever — a 30-day
retention would quietly accumulate every dump ever taken.

Add one lifecycle rule scoped to the `db-backups/` prefix that expires
noncurrent versions after ~30 days:

```json
{
  "Rules": [
    {
      "ID": "DigitVaDbBackupsExpireNoncurrent",
      "Status": "Enabled",
      "Filter": { "Prefix": "db-backups/" },
      "NoncurrentVersionExpiration": { "NoncurrentDays": 30 }
    }
  ]
}
```

This is the **one prefix where a lifecycle rule is appropriate**. Attachments
(`<S3_PREFIX>…/media/`) and SmartVA run archives (`smartva_runs/`) are primary
data with no application-side deletion policy: a lifecycle rule over those
prefixes would destroy data the app still expects to read. Scope the rule to
`db-backups/` and nothing else.

No IAM change is needed. The existing DigitVA bucket policy already grants
Get/Put/Delete on objects and List on the bucket, which is everything the backup
service uses — see
[runtime-and-operations.md](runtime-and-operations.md), *Bucket provisioning
checklist*.

## Making a backup

Scheduled nightly; also available on demand.

```bash
# CLI (dump + retention)
docker compose exec minerva_app_service uv run flask backups db-dump

# Dump but keep every existing dump
docker compose exec minerva_app_service uv run flask backups db-dump --no-prune

# Apply retention on its own
docker compose exec minerva_app_service uv run flask backups db-prune --dry-run
docker compose exec minerva_app_service uv run flask backups db-prune

# What exists
docker compose exec minerva_app_service uv run flask backups db-list --limit 20
```

The admin equivalent is the **Database backups** block on the Attachment
Management panel: the last ten backups with time, status, size, store and object
key, the retention setting, and a *Back up now* button that queues
`run_db_backup`. Admin-only, CSRF-protected, and the object key is the only
identifier in the response — never a host, a credential or a connection string.

`scripts/manual-db-dump.sh` still exists and still works: it produces an
identically named dump on the host from the database container. It is the
fallback for when the app container is not running.

## Restoring

### From the object store

`scripts/manual-db-restore.sh --from-s3 <object_key>` downloads the dump first
and then proceeds exactly as an ordinary restore, including the existing
destructive confirmation:

```bash
# 1. Find the key
docker compose exec minerva_app_service uv run flask backups db-list

# 2. Restore it (the script confirms before anything destructive)
./scripts/manual-db-restore.sh --from-s3 \
  db-backups/minerva/pg_dump_minerva_20260917T013000Z.dump
```

What that does, in order:

1. Asks you to type `YES` to drop and recreate `POSTGRES_DB`.
2. Runs `flask backups db-download` inside `minerva_app_service`, which streams
   the object to a file and **verifies its sha256 against the value recorded in
   `va_db_backups`**. A mismatch removes the file and exits non-zero; a key with
   no recorded checksum is refused outright, so a restore never trusts bytes
   DigitVA cannot vouch for.
3. Copies the verified dump to a temporary directory on the host (removed on
   exit) and continues down the existing path: stop the app containers, confirm
   zero active connections, `dropdb`/`createdb`, `pg_restore --no-owner
   --no-privileges`, sequence-alignment check.
4. Prints the ODK credential-pepper notice and the commands to restart the
   containers and run `flask db upgrade`.

The download needs `minerva_app_service` running; everything after it does not.

### From a local file

Unchanged:

```bash
./scripts/manual-db-restore.sh ~/dailybackups/pg_dump_minerva_20260917T013000Z.dump
```

### Fetching a dump without restoring

```bash
docker compose exec minerva_app_service uv run flask backups db-download \
  db-backups/minerva/pg_dump_minerva_20260917T013000Z.dump /tmp/restore.dump
```

## What is recorded

One `va_db_backups` row per attempt — see
[data-model.md](data-model.md), `va_db_backups`. `status` is `running` before
`pg_dump` starts, so an interrupted run leaves evidence rather than nothing.
`error_code` is a short category (`pg_dump_failed`, `upload_failed`,
`verify_mismatch`, `dump_too_large`, …), never a message from `pg_dump` or the
transport.

## Safety properties

- The database password reaches `pg_dump` through `PGPASSWORD` in its
  environment. It is never in an argument vector, a log line, a CLI output or an
  API response.
- The dump streams from `pg_dump`'s stdout to one temporary file while its size,
  sha256 and md5 are computed in the same pass. Nothing is buffered whole, and
  the temporary file is removed in a `finally` whatever happens.
- The upload is a single `put_object`: atomic, with an ETag that is a plain MD5,
  which is verified along with the object's size. A dump larger than 4.5 GB is
  refused before any upload rather than exceeding that call's limit.
- Any failure after the upload deletes the object, so the bucket never holds an
  unverified dump pretending to be a backup.
- `pg_dump`, `pg_restore` and `psql` (PostgreSQL 17 client) are present in the
  application container; `DATABASE_URL` reaches `minerva_db_service` from there.

## Related operational notes

### Pulling container-owned files off the VM with rsync

Docker/container-created files under `data/smartva_runs` are owned by
`nobody:nogroup`, with many nested directories at `700`, so a normal `rsync` as
an unprivileged user cannot read them. Pulling from a laptop with a remote
`sudo rsync` also fails: `sudo` wants a TTY, and `rsync` opens a separate
non-TTY remote session, so pre-running `ssh -t … "sudo -v"` does not help.

Approach: a narrowly scoped passwordless-sudo wrapper on the server.

```bash
which rsync   # expect /usr/bin/rsync

sudo tee /usr/local/bin/rsync-smartva-read >/dev/null <<'EOF'
#!/bin/sh
exec /usr/bin/rsync "$@"
EOF
sudo chmod 755 /usr/local/bin/rsync-smartva-read

sudo visudo -f /etc/sudoers.d/rsync-smartva-read
#   vivek ALL=(root) NOPASSWD: /usr/local/bin/rsync-smartva-read

sudo chown root:root /etc/sudoers.d/rsync-smartva-read
sudo chmod 0440 /etc/sudoers.d/rsync-smartva-read
sudo visudo -c
sudo -n /usr/local/bin/rsync-smartva-read --version   # no password prompt
```

From the laptop:

```bash
rsync -avh --progress \
  --rsync-path="sudo /usr/local/bin/rsync-smartva-read" \
  digitvaapp:~/app/ ./Digitva_server/
```

Notes: macOS `rsync` does not support `-A`; the trailing slash on `~/app/` copies
the *contents* of `app`; re-running resumes and skips what is already copied.

**Security note:** this grants passwordless sudo for that wrapper, which is
effectively root-read access through it. It is narrower than allowing
passwordless `/usr/bin/rsync`, but it is still privileged access and should be
treated accordingly. With SmartVA run archival to S3 in place, this is largely
historical: run directories are removed from the VM once archived.
