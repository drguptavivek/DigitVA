import logging
import os
from logging.handlers import TimedRotatingFileHandler

from celery.signals import after_setup_logger, after_setup_task_logger

from app import create_app

flask_app = create_app()

# Silence noisy SQLAlchemy INFO logging in Celery worker/beat output
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


def _add_daily_rotating_handler(logger, **kwargs):
    """Attach a daily-rotating file handler to Celery's root/task logger."""
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "celery_tasks.log")
    handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        utc=True,
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)


after_setup_logger.connect(_add_daily_rotating_handler)
after_setup_task_logger.connect(_add_daily_rotating_handler)

celery_app = flask_app.extensions["celery"]

# Register tasks with the worker
import app.tasks.sync_tasks  # noqa: F401, E402

# Seed beat schedule and clean up orphaned run rows on startup
with flask_app.app_context():
    from app.tasks.sync_tasks import (
        cleanup_stale_runs,
        ensure_coding_timeout_cleanup_scheduled,
        ensure_submission_analytics_mv_refresh_scheduled,
        ensure_sync_scheduled,
    )
    cleanup_stale_runs()
    ensure_sync_scheduled()
    ensure_coding_timeout_cleanup_scheduled()
    ensure_submission_analytics_mv_refresh_scheduled()
