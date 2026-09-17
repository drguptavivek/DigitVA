"""Celery task and beat registration for the nightly database backup.

``run_db_backup`` is the scheduled entry point: it dumps the database to the
DigitVA object store and then applies the retention count. The work belongs to
``app/services/db_backup_service.py``; this module only gives the schedule
somewhere to call it from.

The task never raises. A failure is already recorded on a ``va_db_backups`` row
with a short error code, and letting the exception escape would only add a
Celery traceback that says the same thing — while leaving beat to retry a dump
that will fail the same way in a minute. The admin panel is where a failure is
meant to be seen.

The beat schedule itself lives in the database (``sqlalchemy_celery_beat``), so
``ensure_db_backup_scheduled()`` seeds it idempotently on worker startup exactly
as the ODK sync and cleanup schedules do — see ``make_celery.py``.
"""

import logging

import sqlalchemy as sa
from celery import shared_task

log = logging.getLogger(__name__)

# The beat row's name. Also its identity: seeding looks this row up by name, so
# renaming it here creates a second schedule rather than moving this one.
DB_BACKUP_SCHEDULE_NAME = "Database backup — daily"

# Default when DB_BACKUP_DAILY_TIME is missing or unparseable. Chosen for the
# quiet hour after midnight UTC, well clear of the 6-hourly ODK sync.
DEFAULT_DAILY_TIME = "01:30"


@shared_task(
    name="app.tasks.backup_tasks.run_db_backup",
    bind=True,
    soft_time_limit=1800,
    time_limit=2400,
)
def run_db_backup(self, triggered_by="scheduled", user_id=None, prune=True):
    """Dump the database to the object store, then apply retention.

    Returns a counts-only dict — status, store, size, what was pruned — with no
    credential and nothing beyond the object key an operator needs to name the
    dump. Never raises: a failed dump is a ``failed`` row, and the prune is
    skipped when the dump failed so a broken backup run cannot also delete the
    last good dump.
    """
    from app.services import db_backup_service as svc

    try:
        outcome = svc.create_db_backup(triggered_by=triggered_by, user_id=user_id)
    except Exception:  # noqa: BLE001 - a scheduled task must not crash the beat loop
        log.error("db backup task: create failed unexpectedly", exc_info=True)
        return {"status": "failed", "error_code": "unexpected", "pruned": 0}

    result = {
        "status": outcome.status,
        "store": outcome.store,
        "object_key": outcome.object_key,
        "size_bytes": outcome.size_bytes,
        "error_code": outcome.error_code,
        "pruned": 0,
    }
    if not (prune and outcome.ok):
        return result

    try:
        prune_outcome = svc.prune_db_backups()
        result["pruned"] = prune_outcome.pruned
        result["kept"] = prune_outcome.kept
        result["prune_skipped"] = prune_outcome.skipped_reason
    except Exception:  # noqa: BLE001 - a failed prune must not fail a good backup
        log.error("db backup task: prune failed unexpectedly", exc_info=True)
        result["prune_skipped"] = "unexpected"
    return result


def parse_daily_time(value: str | None) -> tuple[int, int]:
    """``"HH:MM"`` as ``(hour, minute)``, falling back to the default.

    An unparseable or out-of-range value is a misconfiguration, not a reason to
    stop backing the database up, so it is logged and the default is used.
    """
    raw = (value or "").strip() or DEFAULT_DAILY_TIME
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(raw)
    except ValueError:
        log.warning(
            "DB_BACKUP_DAILY_TIME is not a valid HH:MM time; using %s",
            DEFAULT_DAILY_TIME,
        )
        hour, minute = (int(part) for part in DEFAULT_DAILY_TIME.split(":"))
    return hour, minute


def ensure_db_backup_scheduled():
    """Seed the daily database backup beat entry. Idempotent.

    Follows the interval-schedule seeders in ``app/tasks/sync_tasks.py``, with a
    crontab row instead of an interval because the time of day matters: a dump
    belongs in the quiet hour, not "every 24 hours from whenever beat restarted".
    Timezone is UTC, the same one the Celery config runs in.
    """
    try:
        from flask import current_app

        from app import db

        hour, minute = parse_daily_time(current_app.config.get("DB_BACKUP_DAILY_TIME"))

        with db.engine.begin() as conn:
            schedule_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_crontabschedule "
                    "WHERE minute = :minute AND hour = :hour AND day_of_week = '*' "
                    "AND day_of_month = '*' AND month_of_year = '*' "
                    "AND timezone = 'UTC' LIMIT 1"
                ),
                {"minute": str(minute), "hour": str(hour)},
            ).scalar()
            if schedule_id is None:
                schedule_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_crontabschedule "
                        "(minute, hour, day_of_week, day_of_month, month_of_year, timezone) "
                        "VALUES (:minute, :hour, '*', '*', '*', 'UTC') RETURNING id"
                    ),
                    {"minute": str(minute), "hour": str(hour)},
                ).scalar()

            existing_schedule_id = conn.execute(
                sa.text(
                    "SELECT schedule_id FROM public.celery_periodictask "
                    "WHERE name = :name LIMIT 1"
                ),
                {"name": DB_BACKUP_SCHEDULE_NAME},
            ).scalar()

            if existing_schedule_id is None:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO public.celery_periodictask
                            (name, task, args, kwargs, queue, exchange, routing_key, headers,
                             priority, one_off, enabled, total_run_count, description,
                             discriminator, schedule_id)
                        VALUES
                            (:name, :task, '[]', '{}', NULL, NULL, NULL, '{}',
                             NULL, false, true, 0, '',
                             'crontabschedule', :schedule_id)
                        """
                    ),
                    {
                        "name": DB_BACKUP_SCHEDULE_NAME,
                        "task": "app.tasks.backup_tasks.run_db_backup",
                        "schedule_id": schedule_id,
                    },
                )
            elif existing_schedule_id != schedule_id:
                # DB_BACKUP_DAILY_TIME changed; point the existing row at the
                # new crontab rather than leaving the old hour in place.
                conn.execute(
                    sa.text(
                        "UPDATE public.celery_periodictask SET schedule_id = :schedule_id, "
                        "discriminator = 'crontabschedule' WHERE name = :name"
                    ),
                    {"schedule_id": schedule_id, "name": DB_BACKUP_SCHEDULE_NAME},
                )
            else:
                return

            conn.execute(
                sa.text(
                    "INSERT INTO public.celery_periodictaskchanged (last_update) "
                    "VALUES (NOW()) ON CONFLICT DO NOTHING"
                )
            )

        log.info(
            "Database backup beat schedule seeded: daily at %02d:%02d UTC.", hour, minute
        )
    except Exception as e:
        log.warning("Could not seed database backup schedule: %s", e)
