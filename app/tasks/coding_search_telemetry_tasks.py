"""Celery task and beat registration for the daily coding-search telemetry
prune (digitva-zpe.3, phase 0).

Phase-0 telemetry is an operational log with a 90-day retention
(docs/policy/coding-search-telemetry.md). The delete itself is one indexed
DELETE (``coding_search_telemetry_service.prune_expired``); this module only
gives the beat loop somewhere to call it from, following the same schedule
seeding pattern as the ODK sync and cleanup entries in ``app/tasks/sync_tasks.py``.
"""

import logging

import sqlalchemy as sa
from celery import shared_task

log = logging.getLogger(__name__)

# The beat row's name. Also its identity: seeding looks this row up by name,
# so renaming it here creates a second schedule rather than moving this one.
TELEMETRY_PRUNE_SCHEDULE_NAME = "Coding search telemetry prune — daily"


@shared_task(
    name="app.tasks.coding_search_telemetry_tasks.prune_coding_search_telemetry_task",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def prune_coding_search_telemetry_task(self):
    """Delete telemetry rows past the 90-day retention. Never raises.

    A failed prune is a warning in the worker log and is retried by the same
    schedule tomorrow; the table is an append-mostly log, so one missed day
    costs nothing that matters.
    """
    from app.services import coding_search_telemetry_service

    try:
        pruned = coding_search_telemetry_service.prune_expired()
    except Exception:  # noqa: BLE001 - a scheduled task must not crash the beat loop
        log.error("coding search telemetry prune failed unexpectedly", exc_info=True)
        return {"pruned": 0, "status": "unexpected"}
    return {"pruned": pruned, "status": "ok"}


def ensure_coding_search_telemetry_prune_scheduled():
    """Seed the daily telemetry prune beat entry. Idempotent.

    Follows the interval-schedule seeders in ``app/tasks/sync_tasks.py``: the
    every-1-day interval row is shared (looked up, created only when missing)
    and the task row is found by name, so re-running this is a no-op.
    """
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
                sa.text(
                    "SELECT id FROM public.celery_periodictask WHERE name = :name LIMIT 1"
                ),
                {"name": TELEMETRY_PRUNE_SCHEDULE_NAME},
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
                        "name": TELEMETRY_PRUNE_SCHEDULE_NAME,
                        "task": (
                            "app.tasks.coding_search_telemetry_tasks."
                            "prune_coding_search_telemetry_task"
                        ),
                        "schedule_id": interval_id,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )

        log.info("Coding search telemetry prune beat schedule seeded: daily.")
    except Exception as e:
        log.warning("Could not seed coding search telemetry prune schedule: %s", e)
