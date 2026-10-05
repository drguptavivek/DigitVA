"""Celery task and beat registration for the daily sign-in IP wipe
(digitva-ci8). ``web_sign_in`` events carry the client IP in ``detail.ip`` for
firewall-log correlation; after ``SIGN_IN_IP_RETENTION_DAYS`` the IP is
removed and the event kept (docs/policy/authentication-factors.md section 9).
Same beat seeding pattern as ``notification_tasks``.
"""

import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from celery import shared_task

log = logging.getLogger(__name__)

# Owner decision 2026-10-01: same retention as the log files.
SIGN_IN_IP_RETENTION_DAYS = 210

# The beat row's name is its identity: renaming it seeds a second schedule.
SIGN_IN_IP_WIPE_SCHEDULE_NAME = "Sign-in IP wipe — daily"
SIGN_IN_IP_WIPE_TASK_NAME = "app.tasks.security_event_tasks.wipe_sign_in_ips_task"


def wipe_sign_in_ips() -> int:
    """Remove ``ip`` from the detail of ``web_sign_in`` events older than the
    retention, in one set-based UPDATE; returns the rows changed. Rows already
    wiped no longer match, so a rerun changes nothing."""
    from app import db
    from app.models import AuthSecurityEvent

    cutoff = datetime.now(UTC) - timedelta(days=SIGN_IN_IP_RETENTION_DAYS)
    result = db.session.execute(
        sa.update(AuthSecurityEvent)
        .where(
            AuthSecurityEvent.event_type == "web_sign_in",
            AuthSecurityEvent.occurred_at < cutoff,
            AuthSecurityEvent.detail.has_key("ip"),
        )
        .values(detail=AuthSecurityEvent.detail.op("-")(sa.cast("ip", sa.Text)))
    )
    db.session.commit()
    return result.rowcount


@shared_task(
    name=SIGN_IN_IP_WIPE_TASK_NAME,
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def wipe_sign_in_ips_task(self):
    """Wipe expired sign-in IPs. Never raises: a failed run is a worker-log
    error and tomorrow's run catches up. Logs a count, never an address."""
    from app import db

    try:
        wiped = wipe_sign_in_ips()
    except Exception:  # noqa: BLE001 - a scheduled task must not crash the beat loop
        db.session.rollback()
        log.error("sign-in IP wipe failed unexpectedly", exc_info=True)
        return {"wiped": 0, "status": "unexpected"}
    log.info("sign-in IP wipe: %d event(s) blanked", wiped)
    return {"wiped": wiped, "status": "ok"}


def ensure_sign_in_ip_wipe_scheduled():
    """Seed the daily wipe beat entry. Idempotent: the every-1-day interval
    row is shared and the task row is found by name."""
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
                sa.text("SELECT id FROM public.celery_periodictask WHERE name = :name LIMIT 1"),
                {"name": SIGN_IN_IP_WIPE_SCHEDULE_NAME},
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
                        "name": SIGN_IN_IP_WIPE_SCHEDULE_NAME,
                        "task": SIGN_IN_IP_WIPE_TASK_NAME,
                        "schedule_id": interval_id,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )
        log.info("Sign-in IP wipe beat schedule seeded: daily.")
    except Exception as e:
        log.warning("Could not seed sign-in IP wipe schedule: %s", e)
