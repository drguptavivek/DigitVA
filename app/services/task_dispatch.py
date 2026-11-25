"""Service-level entry points that queue Celery tasks from app.tasks.sync_tasks.

Services call these instead of importing the task module. Each looks the task
up on sync_tasks at call time (lazy import, as the callers did), which avoids
an import cycle and keeps ``patch("app.tasks.sync_tasks.<task>...")`` working.
Arguments pass through unchanged; failures propagate to the caller.
"""


def load_task_module() -> None:
    """Import app.tasks.sync_tasks now. Callers that imported a task outside
    their try block call this at the same spot, so an import failure still
    raises there instead of inside the try."""
    import app.tasks.sync_tasks  # noqa: F401


def enqueue_smartva_for_submission(**kwargs) -> None:
    """``run_smartva_for_submission.delay(**kwargs)``."""
    from app.tasks.sync_tasks import run_smartva_for_submission

    run_smartva_for_submission.delay(**kwargs)


def enqueue_open_submission_repair(*, va_sid: str, trigger_source: str) -> None:
    """``run_open_submission_repair.delay(va_sid=..., trigger_source=...)``."""
    from app.tasks.sync_tasks import run_open_submission_repair

    run_open_submission_repair.delay(va_sid=va_sid, trigger_source=trigger_source)


def enqueue_cod_bucket_rows_rebuild() -> None:
    """``rebuild_cod_bucket_rows_task.delay()``: rebuild every scheme."""
    from app.tasks.sync_tasks import rebuild_cod_bucket_rows_task

    rebuild_cod_bucket_rows_task.delay()


def enqueue_cod_bucket_scheme_rebuild(scheme_id: str) -> None:
    """``rebuild_cod_bucket_scheme_task.delay(scheme_id)``."""
    from app.tasks.sync_tasks import rebuild_cod_bucket_scheme_task

    rebuild_cod_bucket_scheme_task.delay(scheme_id)
