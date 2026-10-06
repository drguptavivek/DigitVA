"""Celery task and beat registration for the daily purge of web intake
uploads (digitva-i9lb): files of a draft untouched for 30 days, and files no
answer of their draft references any more after 30 days, are deleted with an
audit row per draft (docs/policy/web-intake.md "Attachments"). Same beat
seeding pattern as ``security_event_tasks``.
"""

import logging

import sqlalchemy as sa
from celery import shared_task

log = logging.getLogger(__name__)

# The beat row's name is its identity: renaming it seeds a second schedule.
UPLOAD_PURGE_SCHEDULE_NAME = "Web intake upload purge — daily"
UPLOAD_PURGE_TASK_NAME = "app.tasks.web_intake_upload_tasks.purge_web_intake_uploads_task"


@shared_task(
    name=UPLOAD_PURGE_TASK_NAME,
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def purge_web_intake_uploads_task(self):
    """Purge expired web intake uploads. Never raises: a failed run is a
    worker-log error and tomorrow's run catches up. Logs counts, never names."""
    from app import db
    from app.services import web_intake_attachment_service as attachments

    try:
        result = attachments.purge_expired_uploads()
    except Exception:  # noqa: BLE001 - a scheduled task must not crash the beat loop
        db.session.rollback()
        log.error("web intake upload purge failed unexpectedly", exc_info=True)
        return {"files": 0, "batches": 0, "status": "unexpected"}
    log.info("web intake upload purge: %d file(s) in %d batch(es)", result["files"], result["batches"])
    return {**result, "status": "ok"}


def ensure_web_intake_upload_purge_scheduled():
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
                {"name": UPLOAD_PURGE_SCHEDULE_NAME},
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
                        "name": UPLOAD_PURGE_SCHEDULE_NAME,
                        "task": UPLOAD_PURGE_TASK_NAME,
                        "schedule_id": interval_id,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )
        log.info("Web intake upload purge beat schedule seeded: daily.")
    except Exception as e:
        log.warning("Could not seed web intake upload purge schedule: %s", e)
