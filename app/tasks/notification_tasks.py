"""Celery task and beat registration for the daily notification purge
(digitva-hdrv). Rows older than 30 days are deleted in batches by
``notification_service.purge_expired``; this module gives the beat loop
somewhere to call it from, with the same seeding pattern as
``coding_search_telemetry_tasks``.
"""

import logging

import sqlalchemy as sa
from celery import shared_task

log = logging.getLogger(__name__)

# The beat row's name is its identity: renaming it seeds a second schedule.
NOTIFICATION_PURGE_SCHEDULE_NAME = "User notifications purge — daily"


@shared_task(
    name="app.tasks.notification_tasks.purge_notifications_task",
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def purge_notifications_task(self):
    """Delete notifications past the 30-day retention. Never raises: a failed
    purge is a worker-log error and tomorrow's run catches up."""
    from app.services import notification_service

    try:
        purged = notification_service.purge_expired()
    except Exception:  # noqa: BLE001 - a scheduled task must not crash the beat loop
        log.error("notification purge failed unexpectedly", exc_info=True)
        return {"purged": 0, "status": "unexpected"}
    return {"purged": purged, "status": "ok"}


def ensure_notification_purge_scheduled():
    """Seed the daily purge beat entry. Idempotent: the every-1-day interval
    row is shared and the task row is found by name."""
    try:
        from app import db

        with db.engine.begin() as conn:
            interval_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_intervalschedule "
                    "WHERE every = 1 AND period = 'days' LIMIT 1"
                )
            ).scalar()
            if interval_id is None:
                interval_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_intervalschedule (every, period) "
                        "VALUES (1, 'days') RETURNING id"
                    )
                ).scalar()

            exists = conn.execute(
                sa.text("SELECT id FROM public.celery_periodictask WHERE name = :name LIMIT 1"),
                {"name": NOTIFICATION_PURGE_SCHEDULE_NAME},
            ).scalar()
            if not exists:
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
                             'intervalschedule', :schedule_id)
                        """
                    ),
                    {
                        "name": NOTIFICATION_PURGE_SCHEDULE_NAME,
                        "task": "app.tasks.notification_tasks.purge_notifications_task",
                        "schedule_id": interval_id,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )
        log.info("Notification purge beat schedule seeded: daily.")
    except Exception as e:
        log.warning("Could not seed notification purge schedule: %s", e)
