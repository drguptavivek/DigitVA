import logging
import os
from logging.handlers import TimedRotatingFileHandler

from celery.signals import after_setup_logger, after_setup_task_logger

from app import create_app
from app.logging.va_logger import setup_slow_query_logging

flask_app = create_app()

# Silence noisy SQLAlchemy INFO logging in Celery worker/beat output
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

# Slow-query logging for Celery — all statement types at a 1s threshold,
# covering REFRESH MATERIALIZED VIEW and heavy SELECT aggregations that
# the Flask write-only filter would miss.
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
setup_slow_query_logging(
    log_file=os.path.join(_log_dir, "celery_slow_queries.log"),
    threshold_s=1.0,
    logger_name='celery_slow_sql',
    all_statements=True,
    stderr=True,
)


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
