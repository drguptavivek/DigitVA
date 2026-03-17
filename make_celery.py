import logging
from app import create_app

flask_app = create_app()

# Silence noisy SQLAlchemy INFO logging in Celery worker/beat output
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

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
