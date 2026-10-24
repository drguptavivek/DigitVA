"""Celery task: machine-translate the missing Expo UI strings (digitva-cqw9)."""

import logging

from celery import shared_task

log = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.ui_string_tasks.machine_translate_ui_strings",
    bind=True,
    soft_time_limit=14400,
    time_limit=14700,
)
def machine_translate_ui_strings(self, locales=None):
    """Create machine candidates for the missing strings. Never raises: the
    outcome is the returned state and the status the admin page reads."""
    from app.services import ui_string_machine_job as job

    try:
        return job.run(locales)
    except Exception as exc:  # noqa: BLE001 - a failed run is a log line and a status
        log.error("ui string machine translation failed: %s", type(exc).__name__, exc_info=True)
        return {"state": "failed", "error": str(exc)}
