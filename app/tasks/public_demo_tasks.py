"""Celery task and beat registration for the public demo's daily purge
(digitva-77v5.6; docs/policy/public-demo.md section 9).

The task deletes public-demo accounts idle for ``PUBLIC_DEMO_PURGE_IDLE_DAYS``
and everything they created (``public_demo_purge_service.purge_run``). It does
nothing, and says why in its result, unless ``PUBLIC_DEMO_ENABLED`` and
``PUBLIC_DEMO_PURGE_ENABLED`` are on and the database holds no project but the
demo's. Logs and the audit row carry counts only.
"""

import logging

from celery import shared_task

log = logging.getLogger(__name__)

# The beat row's name is its identity: renaming it seeds a second schedule.
PUBLIC_DEMO_PURGE_SCHEDULE_NAME = "Public demo purge — daily"
PUBLIC_DEMO_PURGE_TASK_NAME = "app.tasks.public_demo_tasks.purge_public_demo_task"
PUBLIC_DEMO_PURGE_INTERVAL_SECONDS = 24 * 60 * 60


@shared_task(name=PUBLIC_DEMO_PURGE_TASK_NAME, bind=True, soft_time_limit=1500, time_limit=1800)
def purge_public_demo_task(self):
    """Run the purge. Never raises: a failed run is a worker-log error and
    tomorrow's run catches up. Returns the run summary (counts only)."""
    from app import db
    from app.services import public_demo_purge_service

    try:
        result = public_demo_purge_service.purge_run(apply=True)
    except Exception:  # noqa: BLE001 - a scheduled task must not crash the beat loop
        db.session.rollback()
        log.error("public demo purge failed unexpectedly", exc_info=True)
        return {"status": "unexpected", "accounts": 0}
    return {"status": result["status"], "accounts": result["accounts"], "failed": result["failed"]}


def ensure_public_demo_purge_scheduled():
    """Seed the daily purge beat entry. Idempotent."""
    from app.tasks.sync_tasks import _ensure_interval_task

    try:
        if _ensure_interval_task(
            PUBLIC_DEMO_PURGE_SCHEDULE_NAME, PUBLIC_DEMO_PURGE_TASK_NAME,
            PUBLIC_DEMO_PURGE_INTERVAL_SECONDS,
        ):
            log.info("Public demo purge beat schedule seeded: daily.")
    except Exception as e:  # noqa: BLE001
        log.warning("Could not seed public demo purge schedule: %s", e)
