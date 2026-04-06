"""Async CSV export tasks — offloaded from the Flask request cycle.

Each task generates a CSV file on disk under ``<APP_DATA>/exports/`` and stores
metadata (filename, row count) in the Celery result backend so the API can poll
for completion and serve the file.
"""

import logging
import os
import time

from celery import shared_task
from celery.utils.log import get_task_logger

log = get_task_logger(__name__)

_EXPORT_FUNCTIONS = {}  # lazy registry, populated on first call


def _get_export_fn(kind: str):
    """Lazy-import to avoid circulars at module level."""
    if kind not in _EXPORT_FUNCTIONS:
        from app.services.data_management_service import (
            dm_submissions_export_csv,
            dm_smartva_input_export_csv,
            dm_smartva_likelihoods_export_csv,
            dm_smartva_results_export_csv,
        )

        _EXPORT_FUNCTIONS.update(
            {
                "data": dm_submissions_export_csv,
                "smartva_input": dm_smartva_input_export_csv,
                "smartva_results": dm_smartva_results_export_csv,
                "smartva_likelihoods": dm_smartva_likelihoods_export_csv,
            },
        )
    return _EXPORT_FUNCTIONS[kind]


def _export_dir() -> str:
    from flask import current_app

    d = os.path.join(current_app.config["APP_DATA"], "exports")
    os.makedirs(d, exist_ok=True)
    return d


@shared_task(bind=True, time_limit=300, soft_time_limit=270)
def run_csv_export(self, export_kind: str, user_id: str, filters: dict):
    """Generate a CSV export and write it to disk.

    Returns a dict with ``filename`` and ``rows`` so the polling endpoint can
    report progress.
    """
    from flask import current_app
    from app import db
    from app.models import VaUsers

    t0 = time.monotonic()
    log.info("Export %s started (task=%s, user=%s)", export_kind, self.request.id, user_id)

    user = db.session.get(VaUsers, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")

    export_fn = _get_export_fn(export_kind)
    csv_text = export_fn(user, **filters)

    out_dir = _export_dir()
    filepath = os.path.join(out_dir, f"{self.request.id}.csv")
    with open(filepath, "w", encoding="utf-8", newline="") as fh:
        fh.write(csv_text)

    row_count = csv_text.count("\n") - 1  # subtract header
    elapsed = time.monotonic() - t0
    log.info(
        "Export %s finished (task=%s, rows=%d, %.1fs)",
        export_kind,
        self.request.id,
        row_count,
        elapsed,
    )

    # Stale-file cleanup: remove exports older than 2 hours
    _cleanup_old_exports(out_dir, max_age_hours=2)

    return {
        "filename": f"export-{export_kind}.csv",
        "rows": row_count,
        "filepath": filepath,
    }


def _cleanup_old_exports(directory: str, max_age_hours: int = 2) -> int:
    """Remove CSV export files older than *max_age_hours*."""
    import time as _t

    cutoff = _t.time() - max_age_hours * 3600
    removed = 0
    for name in os.listdir(directory):
        if not name.endswith(".csv"):
            continue
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("Cleaned up %d old export files", removed)
    return removed
