"""Celery task and beat registration for the daily TLS certificate check.

``run_tls_health_check`` rebuilds the health report (certificates and the S3
store), caches it for the admin banner, and while anything needs attention emails
every active admin.
The checks live in ``app/services/tls_health_service.py``; the schedule is seeded
the same way as the database backup (``backup_tasks.seed_daily_crontab_task``).

The task never raises. A failed check is already an ``error`` row, and a failed
mail is logged by the email service, so the beat loop is not stopped by either.
"""

import logging
from collections import Counter

import sqlalchemy as sa
from celery import shared_task
from flask import current_app

log = logging.getLogger(__name__)

# The beat row's name. Also its identity: renaming it creates a second schedule.
TLS_HEALTH_SCHEDULE_NAME = "TLS certificate health — daily"
TLS_HEALTH_TASK_NAME = "app.tasks.tls_health_tasks.run_tls_health_check"

# Default when TLS_HEALTH_DAILY_TIME is missing or unparseable.
DEFAULT_DAILY_TIME = "06:30"


@shared_task(
    name=TLS_HEALTH_TASK_NAME,
    soft_time_limit=300,
    time_limit=400,
)
def run_tls_health_check():
    """Check every certificate and the S3 store, cache the report, and mail admins if one is due.

    Returns a counts-only dict by status. Mails go only when the report needs
    attention, one per active admin, and never carry more than the report rows.
    """
    from app.services import tls_health_service as svc
    from app.services.email_service import send_tls_expiry_notice

    rows = svc.certificate_report()
    svc.store_report(rows)
    counts = Counter(row["status"] for row in rows)
    log.info("TLS health check: %s", ", ".join(f"{s}={n}" for s, n in sorted(counts.items())))

    result = {"status_counts": dict(counts), "notified": 0}
    if not svc.needs_attention(rows):
        return result

    for admin in _active_admins():
        if send_tls_expiry_notice(admin, rows):
            result["notified"] += 1
    return result


def _active_admins() -> list:
    """Active users holding an active global admin grant, with an email on file."""
    from app import db
    from app.models import (
        VaAccessRoles,
        VaAccessScopeTypes,
        VaStatuses,
        VaUserAccessGrants,
        VaUsers,
    )

    stmt = (
        sa.select(VaUsers)
        .join(VaUserAccessGrants, VaUserAccessGrants.user_id == VaUsers.user_id)
        .where(
            VaUsers.user_status == VaStatuses.active,
            VaUserAccessGrants.role == VaAccessRoles.admin,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUsers.email.isnot(None),
        )
        .distinct()
    )
    return list(db.session.scalars(stmt).all())


def ensure_tls_health_scheduled():
    """Seed the daily TLS health beat entry at TLS_HEALTH_DAILY_TIME. Idempotent."""
    from app.tasks.backup_tasks import parse_daily_time, seed_daily_crontab_task

    hour, minute = parse_daily_time(
        current_app.config.get("TLS_HEALTH_DAILY_TIME"),
        default=DEFAULT_DAILY_TIME,
        setting="TLS_HEALTH_DAILY_TIME",
    )
    seed_daily_crontab_task(
        TLS_HEALTH_SCHEDULE_NAME,
        TLS_HEALTH_TASK_NAME,
        hour,
        minute,
        label="TLS health check",
    )
