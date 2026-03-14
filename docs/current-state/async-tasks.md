---
title: Asynchronous Background Tasks
doc_type: current-state
status: active
owner: maintainers
last_updated: 2026-03-14
---

# Asynchronous Background Tasks

DigitVA uses **Celery** with **Redis** for background task execution and **Celery Beat** backed by PostgreSQL for periodic scheduling.

## Architecture

| Component | Container | Role |
|-----------|-----------|------|
| Redis | `minerva_redis_service` | Broker and result backend |
| Celery worker | `minerva_celery_worker` | Executes tasks from the queue |
| Celery Beat | `minerva_celery_beat` | Enqueues periodic tasks on schedule |

Beat uses `sqlalchemy_celery_beat.schedulers:DatabaseScheduler`. The schedule is stored in the `minerva` PostgreSQL database, so interval changes take effect without restarting Beat.

## Flask App Context

`celery_init_app()` in `app/__init__.py` wraps every task in `flask_app.app_context()` via a custom `FlaskTask` class. Tasks have full access to `db.session`, Flask config, and all app utilities.

## Configuration (`config.py`)

```python
CELERY = {
    "broker_url":      "redis://minerva_redis_service:6379/0",
    "result_backend":  "redis://minerva_redis_service:6379/0",
    "beat_dburi":      "postgresql://minerva:minerva@minerva_db_service:5432/minerva",
    "task_ignore_result": True,
    "timezone": "UTC",
    "enable_utc": True,
}
```

## Startup Sequence (`make_celery.py`)

On worker/beat startup `make_celery.py`:

1. Creates the Flask app via `create_app()`
2. Retrieves `celery_app` from `flask_app.extensions["celery"]`
3. Imports `app.tasks.sync_tasks` to register tasks with the worker
4. Calls `cleanup_stale_runs()` — marks orphaned `running` sync rows as `error`
5. Calls `ensure_sync_scheduled()` — idempotently seeds the ODK sync beat entry

## Registered Tasks

### `app.tasks.sync_tasks.run_odk_sync`

Defined in [`app/tasks/sync_tasks.py`](../../app/tasks/sync_tasks.py).

**Purpose:** Run the full ODK data sync and record the outcome in `va_sync_runs`.

**Signature:**
```python
run_odk_sync(triggered_by="scheduled", user_id=None)
```

**Behavior:**
1. Writes a `VaSyncRun` row with `status="running"` and commits immediately (dashboard sees it)
2. Calls `va_data_sync_odkcentral()` — incremental per-form pipeline (delta check → OData fetch → upsert → ETag attachment sync → per-form commit)
3. On success: updates with `status="success"` and metric counts
4. On partial success (some forms failed): updates with `status="partial"` and lists failed form IDs in `error_message`
5. On error: updates with `status="error"` and `error_message`, then re-raises so Celery marks the task failed

**Limits:** `soft_time_limit=1800s`, `time_limit=3600s`

**Default schedule:** every 6 hours via Celery Beat (seeded by `ensure_sync_scheduled()`)

**Manual dispatch:**
```python
from app.tasks.sync_tasks import run_odk_sync
run_odk_sync.delay(triggered_by="manual", user_id=str(user_id))
```

---

### `app.tasks.sync_tasks.run_single_form_sync`

Defined in [`app/tasks/sync_tasks.py`](../../app/tasks/sync_tasks.py).

**Purpose:** Force-resync a single form, bypassing the delta check entirely.

**Signature:**
```python
run_single_form_sync(form_id: str, triggered_by: str = "manual")
```

**Behavior:**
1. Looks up the `va_forms` row for `form_id`
2. Fetches all submissions via OData JSON (no `since` filter — downloads everything)
3. Upserts submissions, syncs attachments (ETag-based), rebuilds CSV
4. Updates `mapping.last_synced_at`

**When to use:** A form failed during a full sync run (status `partial`), or attachments are suspected to be out of sync. Triggered from the per-form sync button in the admin coverage table via `POST /admin/api/sync/form/<form_id>`.

**Manual dispatch:**
```python
from app.tasks.sync_tasks import run_single_form_sync
run_single_form_sync.delay(form_id="UNSW01KA0101", triggered_by="manual")
```

---

### `app.tasks.sync_tasks.run_smartva_pending`

**Purpose:** Run SmartVA analysis on submissions that have no SmartVA result yet, without triggering an ODK download.

Triggered from the admin dashboard "Gen SmartVA" button via `POST /admin/api/sync/trigger-smartva`.

---

## Beat Schedule Tables

The `sqlalchemy_celery_beat` scheduler creates these tables in the `public` schema:

| Table | Purpose |
|-------|---------|
| `celery_periodictask` | One row per scheduled task |
| `celery_intervalschedule` | Interval definitions (every N hours/minutes/etc.) |
| `celery_crontabschedule` | Cron-style definitions |
| `celery_periodictaskchanged` | Signals Beat to reload after a schedule change |

The `discriminator` column on `celery_periodictask` identifies the schedule type (`intervalschedule`, `crontabschedule`, etc.).

Schedule changes made via the admin sync dashboard update `celery_periodictask.schedule_id` and insert a row into `celery_periodictaskchanged` to trigger an immediate Beat reload.

## Defining New Tasks

Use `@shared_task` (requires `celery_app.set_default()` to have been called, which `celery_init_app` does):

```python
from celery import shared_task
from app import db

@shared_task(name="app.tasks.my_module.my_task", bind=True)
def my_task(self, some_arg):
    # db.session and Flask config available here
    ...
```

Register the task with the worker by importing the module in `make_celery.py`:

```python
import app.tasks.my_module  # noqa: F401
```

## Troubleshooting

- **Task not found by worker:** Ensure the task module is imported in `make_celery.py`.
- **Beat not running scheduled tasks:** Check `celery_periodictask.enabled = true` and `celery_periodictaskchanged` has a recent row. Restart `minerva_celery_beat` if needed.
- **Beat DB table errors on cold start:** Beat waits 10 s at startup to allow `flask db upgrade` to complete first. If tables are still missing, run `flask db upgrade` manually and restart Beat.
- **Orphaned `running` sync rows:** Cleaned automatically on next worker startup by `cleanup_stale_runs()`.
