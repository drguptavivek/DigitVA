---
title: CLI Reference
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-17
---

# CLI Reference

All commands run inside the application container:

```
docker compose exec minerva_app_service uv run flask <group> <command> [options]
```

---

## `seed` — Bootstrap data

| Command | Description |
|---------|-------------|
| `seed run` | Seed languages, admin user, form types, field mappings. Safe to re-run. |
| `seed run --test` | Also create 5 test coder users (see [CLAUDE.md](../../CLAUDE.md) for credentials). |

---

## `users` — User management

Detailed policy: [`docs/policy/user-management-cli.md`](../policy/user-management-cli.md)

| Command | Description |
|---------|-------------|
| `users list` | List all users with status and admin state. |
| `users search --query=FRAG` | Search by email or display name (case-insensitive). |
| `users list-grants [--email=...]` | List access grants, optionally filtered by user. |
| `users create --email=... --name=... --password=...` | Create a user (no grants assigned). |
| `users reset-password --email=... --password=...` | Reset a user's password. |
| `users grant-admin --email=...` | Grant or reactivate global admin. |
| `users revoke-admin --email=...` | Deactivate global admin grant. |
| `users set-status --email=... --status=active\|deactive` | Activate or deactivate a user. |

Additional `users create` options: `--landing-page` (default: `coder`), `--timezone` (default: `Asia/Kolkata`), `--language` (repeatable), `--email-verified/--email-unverified`.

---

## `form-types` — Form type management

| Command | Description |
|---------|-------------|
| `form-types list` | List all registered active form types. |
| `form-types register --code=... --name=...` | Register a new form type. Options: `--description`, `--template`. |
| `form-types stats --code=...` | Show statistics for a form type. |
| `form-types deactivate --code=...` | Soft-delete a form type (confirms first). |

---

## `odk-sync` — ODK Central schema sync

| Command | Description |
|---------|-------------|
| `odk-sync choices --form-type=... --project-id=N --form-id=...` | Sync choice mappings from ODK Central. Add `--dry-run` to preview. |
| `odk-sync detect-changes --form-type=... --project-id=N --form-id=...` | Detect schema drift between ODK Central and the database. |

---

## `odk-mappings` — ODK form mapping audit

An ODK form — `(ODK connection, odk_project_id, odk_form_id)` — may be mapped to at
most one `(project_id, site_id)` pair. The rule is enforced in the service layer
(`app/services/odk_form_mapping_service.py`), not by a database constraint, because
the connection is resolved per project through `map_project_odk`.

| Command | Description |
|---------|-------------|
| `odk-mappings audit` | Dry-run. List every ODK form mapped to more than one project-site, with each target's `va_project_sites` status and submission count. |
| `odk-mappings audit --fix` | Delete stale duplicates only: a mapping on a **deactivated** project-site whose ODK form is still mapped to an **active** pair. Idempotent. |

`--fix` refuses (non-zero exit, nothing deleted) when two conflicting mappings are
both on active project-sites: choosing which one survives is a human decision. Use
the Project Forms admin panel to remove the wrong one.

---

## `analytics` — Materialized view maintenance

| Command | Description |
|---------|-------------|
| `analytics refresh-submission-mv` | Refresh all three submission analytics MVs. |
| `analytics refresh-submission-mv --concurrently` | Refresh without blocking reads (recommended for production). |

---

## `payload-backfill` — Enrichment and workflow repair

| Command | Description |
|---------|-------------|
| `payload-backfill status` | Show unenriched vs enriched payload version counts per form. |
| `payload-backfill enrich` | Target active payloads missing enrichment metadata, then run the shared current-payload repair engine per submission: payload revalidation, attachment repair/migration, and current-payload SmartVA follow-through. |

### `enrich` options

| Option | Default | Description |
|--------|---------|-------------|
| `--form-id=ID` | all | Restrict to a single form. |
| `--batch-size=N` | 10 | Submissions per commit. |
| `--max-forms=N` | all | Stop after N forms. |
| `--max-per-form=N` | all | Cap submissions per form. |
| `--dry-run` | off | Run stage checks only (metadata/attachment/SmartVA counts) but write nothing. |

`payload-backfill enrich` now emits a run-scoped log path at start/end:

- `logs/payload_backfill_enrich_<UTC_TIMESTAMP>_<RUN_ID>.log`
- this file contains full per-stage logs for that specific CLI invocation

`payload-backfill enrich` now shares the same per-submission repair engine used
by coding-route on-demand repair, but it still chooses candidates using the CLI
backfill scope rather than the admin form backfill scheduler.

---

## `repair` — Targeted administrative repairs

| Command | Description |
|---------|-------------|
| `repair reactivate-step1-after-final` | Dry-run the historical Step 1 reactivation repair for active coder-final chains. |
| `repair reactivate-step1-after-final --apply` | Reactivate the linked Step 1 row when it was deactivated by the old final-COD behavior and no conflicting active Step 1 exists for the same SID/author. |

Optional filters:

- `--sid=...` to restrict to one submission
- `--limit=N` to cap inspected candidates

---

## `attachments` — Attachment lifecycle

Every command here is a thin wrapper over
[`app/services/attachment_service.py`](../../app/services/attachment_service.py);
the CLI parses options and prints, and the service decides.

| Command | Description |
|---------|-------------|
| `attachments overview [--project-id X]` | Print the same figures as the admin Attachment Management panel: per-form counts by `source_state`, `derivative_state`, `store_state` and `local_fallback_state`, retired-submission attachment rows, rows still awaiting S3 upload, this process's delivery outcome counters, and source error categories. Bulk aggregates only — no filesystem, store or Central access, and no paths, keys or submission identifiers in the output. |
| `attachments central-fetch <PROJECT_ID>` | Report whether store misses may be self-healed from ODK Central for this project (default action). |
| `attachments central-fetch <PROJECT_ID> --enable` | Allow a store miss on a live submission to be fetched from the project's ODK Central connection, streamed to the browser, and written into DigitVA's store. |
| `attachments central-fetch <PROJECT_ID> --disable` | Return the project to store-only delivery: a store miss is a `404`, as before. |

The flag is `va_project_master.attachment_central_fetch_enabled` and defaults to
off. Delivery always reads DigitVA's own store first, so disabling is a complete
rollback with no data change. The same switch is exposed at
`PUT /admin/api/projects/<project_id>/attachment-central-fetch` and as a toggle
in the admin Projects panel. See
[the attachment storage policy](../policy/attachment-storage.md).

### Local -> S3 cutover

Both commands require `ATTACHMENT_STORE=s3` and refuse to run otherwise.
Neither ever deletes an attachment.

| Command | Description |
|---------|-------------|
| `attachments s3-upload [--form-id X] [--dry-run] [--limit N] [--workers N]` | Copy every local attachment blob that is not yet recorded as S3-stored into the bucket, verify it (size, and ETag against the local MD5 for single-part uploads), then set `store_state='s3'` and `local_path=NULL`. Streams from the file, reads rows in keyset pages, idempotent and resumable, and exits non-zero if any row failed. Local files are left in place. |
| `attachments local-quarantine [--form-id X] [--dry-run] [--include-retained]` | Move the local file of each verified `store_state='s3'` row into `APP_DATA/<form_id>/media/.s3-uploaded/` and mark it `local_fallback_state='quarantined'`. A row whose object is not in the bucket is left alone. Archival copies of submissions retired from ODK (`local_fallback_state='retained'`) are skipped unless `--include-retained` is given. |

```
docker compose exec minerva_app_service uv run flask attachments s3-upload --dry-run
docker compose exec minerva_app_service uv run flask attachments s3-upload --workers 8
docker compose exec minerva_app_service uv run flask attachments local-quarantine --dry-run
docker compose exec minerva_app_service uv run flask attachments local-quarantine
```

Verify what landed with the integrity check, which reports and never deletes:

```
docker compose exec minerva_app_service uv run python scripts/check_attachment_integrity.py --store s3
```

Removing the quarantined files after the retention window is a deliberate
manual step — see
[the cutover runbook](runtime-and-operations.md#attachment-delivery).

## `smartva` — SmartVA run archive

Thin wrappers over
[`app/services/smartva_run_archive_service.py`](../../app/services/smartva_run_archive_service.py).
A SmartVA run directory is a working area the SmartVA CLI needs while it runs;
nothing in the app reads it afterwards, so it is archived to the DigitVA bucket
under `smartva_runs/{project_id}/{form_id}/{form_run_id}/` and removed from the
VM. Both commands do nothing on `ATTACHMENT_STORE=local`.

| Command | Description |
|---------|-------------|
| `smartva archive-runs [--form-id X] [--dry-run] [--limit N] [--delete-local]` | Archive every run directory not yet verified in the bucket, plus any archived run whose local copy is still waiting out `SMARTVA_RUNS_KEEP_LOCAL_DAYS`. Uploads with a content type per extension, verifies the whole prefix with one listing, and — with `--delete-local`, off by default — removes the directory and NULLs `disk_path` once verified and once the keep-days window has elapsed. Keyset-paginated, idempotent and resumable; exits non-zero if any run failed. Never deletes on any failure. |
| `smartva archive-status [--form-id X]` | Print run counts by `archive_state`, the number of run directories and bytes still on this VM, the configured key prefix and keep-days, and the most recent failure category. Counts only — no paths, keys or submission identifiers. |

```
docker compose exec minerva_app_service uv run flask smartva archive-status
docker compose exec minerva_app_service uv run flask smartva archive-runs --dry-run
docker compose exec minerva_app_service uv run flask smartva archive-runs --delete-local
```

The admin equivalent is *Archive pending runs* in the Attachment Management
panel, which queues a bounded `run_smartva_run_archive` Celery task. Archived
objects are never presigned and never served. Baseline:
[SmartVA Generation Policy](../policy/smartva-generation-policy.md).

## `backups` — Database backups

Thin wrappers over
[`app/services/db_backup_service.py`](../../app/services/db_backup_service.py).
A `pg_dump -Fc` of the application database goes to the DigitVA bucket under
`db-backups/{db_name}/` and the VM keeps no dump history; on
`ATTACHMENT_STORE=local` the same dump lands in `DB_BACKUP_LOCAL_DIR` and is
pruned there the same way. The database password reaches `pg_dump` through
`PGPASSWORD` and never appears in an argument vector or in any output below.

| Command | Description |
|---------|-------------|
| `backups db-dump [--no-prune]` | Dump the database, verify it in the store, then apply `DB_BACKUP_KEEP_DAILY`. Prints status, size, object key and sha256. Exits non-zero if the dump failed. `--no-prune` keeps every existing dump. |
| `backups db-prune [--dry-run]` | Delete every dump beyond the newest `DB_BACKUP_KEEP_DAILY`, ordered by the UTC timestamp in each dump's name. Never deletes the newest; skips entirely if the store listing fails. `--dry-run` reports the settings and deletes nothing. |
| `backups db-list [--limit N]` | Recent backups from `va_db_backups`: time, status, store, size and object key, plus the store, prefix, retention and scheduled time. |
| `backups db-download <object_key> <dest_path>` | Stream one dump out of the store to a local path and verify its sha256 against the value recorded when it was made. Refuses a key with no recorded checksum; removes the file on a mismatch. |

```
docker compose exec minerva_app_service uv run flask backups db-list
docker compose exec minerva_app_service uv run flask backups db-dump
docker compose exec minerva_app_service uv run flask backups db-prune --dry-run
docker compose exec minerva_app_service uv run flask backups db-download \
  db-backups/minerva/pg_dump_minerva_20260917T013000Z.dump /tmp/restore.dump
```

The admin equivalent is *Back up now* in the Database backups block of the
Attachment Management panel, which queues the `run_db_backup` Celery task — the
same task the daily beat entry runs. Backup objects are never presigned and
never served. Runbook: [Backup And Restore](backup.md).
