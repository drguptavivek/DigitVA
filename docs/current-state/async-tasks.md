---
title: Asynchronous Background Tasks
doc_type: technical_reference
status: active
owner: maintainers
last_updated: 2026-03-10
---

# Asynchronous Background Tasks

DigitVA leverages **Celery** with **Redis** to offload long-running, CPU-bound, or network-bound tasks from the main synchronous Flask application. We also use **Celery Beat** backed by the primary Postgres database for periodic cron-like scheduling.

## Architecture

* **Broker & Result Backend:** Redis (`minerva_redis_service`)
* **Task Queue Worker:** Celery (`minerva_celery_worker`) executes background jobs.
* **Task Scheduler:** Celery Beat (`minerva_celery_beat`) triggers periodic tasks using `celery-sqlalchemy-scheduler`. State is stored directly in the `minerva_db` Postgres database.
* **Context:** The celery initialization (`celery_init_app` in `app/__init__.py`) wraps each task in a `flask_app.app_context()`. This ensures that background tasks have full access to Flask configuration, the SQLAlchemy database session (`db.session`), and logging.

## Core Components

1. **Redis Container** (`minerva_redis_service`): Standard Redis 7 instance used for task queueing and message brokering.
2. **Celery Worker** (`minerva_celery_worker`):
   * Runs the command: `uv run celery -A make_celery:celery_app worker --loglevel=info`
   * Consumes messages off the Redis queue and processes them asynchronously.
3. **Celery Beat** (`minerva_celery_beat`):
   * Runs the command: `uv run celery -A make_celery:celery_app beat --loglevel=info -S celery_sqlalchemy_scheduler.schedulers:DatabaseScheduler`
   * Looks up the periodic schedule from the database and posts matching tasks to the queue.

## Configuration

Configuration variables are dynamically loaded into `app.config["CELERY"]` from `config.py` using `REDIS_URL` and `DATABASE_URL`:

* `broker_url` -> `redis://minerva_redis_service:6379/0`
* `result_backend` -> `redis://minerva_redis_service:6379/0`
* `beat_dburi` -> `postgresql://minerva:minerva@minerva_db_service:5432/minerva`

## Creating a Background Task

Tasks are defined using the `@celery_app.task` decorator. Since the `celery_app` extension proxies standard Celery behavior, you can define tasks anywhere in your services.

**Example Task Definition:**

```python
from celery import shared_task
from app import db
from app.models.va_users import VaUsers

@shared_task(bind=True)
def example_background_task(self, user_id):
    # The Flask app context is automatically provided!
    user = db.session.get(VaUsers, user_id)
    if user:
        # Perform long-running logic here...
        pass
    return True
```

**Dispatching a Task:**

```python
from app.services.my_service import example_background_task

# Fire and forget
example_background_task.delay(user_id="1234")
```

## Adding Periodic Tasks (Database Scheduler)

Because we use `celery-sqlalchemy-scheduler`, periodic tasks can be managed directly via SQL tables (e.g. `celery_periodic_task`). The system automatically syncs changes without requiring a Beat restart. To add a recurring job (like nightly ODK syncs), insert the scheduling configuration into these tables, or use a custom admin interface.

## Troubleshooting

- **Worker Not Finding DB Models:** Ensure imports are correct and `make_celery.py` is successfully building the Flask app.
- **Beat Database Errors:** The Beat container waits 10 seconds before starting to allow the `minerva_app_service` to run `flask db upgrade` first. If Beat fails with missing tables, manually trigger `flask db upgrade` and restart the container.
