"""Celery task: machine-draft the missing questionnaire translations (digitva-m2ve)."""

import logging

from celery import shared_task

log = logging.getLogger(__name__)


@shared_task(
    name="app.tasks.instrument_translation_tasks.machine_translate_instrument",
    bind=True,
    soft_time_limit=14400,
    time_limit=14700,
)
def machine_translate_instrument(self, locales=None):
    """Never raises: the outcome is the returned state and the admin-page status."""
    from app.services import instrument_translation_machine_job as job

    try:
        return job.run(locales)
    except Exception as exc:  # noqa: BLE001 - a failed run is a log line and a status
        log.error("instrument machine translation failed: %s", type(exc).__name__, exc_info=True)
        return {"state": "failed", "error": str(exc)}
