---
title: CLI Reference
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-04-06
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
| `payload-backfill enrich` | Fetch missing ODK metadata (FormVersion, DeviceID, AttachmentsExpected, etc.) from ODK Central. |
| `payload-backfill transition-stuck` | Advance `attachment_sync_pending` submissions that have complete metadata + attachments through the workflow. |

### `enrich` options

| Option | Default | Description |
|--------|---------|-------------|
| `--form-id=ID` | all | Restrict to a single form. |
| `--batch-size=N` | 10 | Submissions per commit. |
| `--max-forms=N` | all | Stop after N forms. |
| `--max-per-form=N` | all | Cap submissions per form. |
| `--dry-run` | off | Fetch metadata but write nothing. |

### `transition-stuck` options

| Option | Default | Description |
|--------|---------|-------------|
| `--batch-size=N` | 100 | Transitions per commit. |
| `--dry-run` | off | Report counts only. |

**Workflow transitions applied:**

- `attachment_sync_pending` → `smartva_pending` (when metadata + attachments are complete)
- `smartva_pending` → `ready_for_coding` (when SmartVA result already exists)

---

## `migrate-attachments` — Storage name migration (one-time)

| Command | Description |
|---------|-------------|
| `migrate-attachments run` | Assign deterministic `storage_name` to attachment rows missing one (dry-run by default). |
| `migrate-attachments run --apply` | Actually write the updates. Idempotent — safe to re-run after a crash. |
