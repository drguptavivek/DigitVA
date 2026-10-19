"""Celery task and beat registration for the synthetic organization demo.

The service owns all demo data, backup, locking and idempotency rules. This
module only provides the scheduled entry point and its database-backed beat
row, so importing Celery never seeds or resets a project.
"""

import logging

import sqlalchemy as sa
from celery import shared_task
from flask import current_app

log = logging.getLogger(__name__)

WEEKLY_DEMO_SCHEDULE_NAME = "DigitVA synthetic organization demo reset — weekly"
WEEKLY_DEMO_TASK_NAME = "app.tasks.organization_demo_tasks.reset_weekly_demo_task"
WEEKLY_DEMO_TIMEZONE = "Asia/Kolkata"


@shared_task(
    name=WEEKLY_DEMO_TASK_NAME,
    soft_time_limit=1800,
    time_limit=2400,
)
def reset_weekly_demo_task():
    """Reset the configured demo project, returning a counts-only result."""
    from app.services import synthetic_demo_service as service

    try:
        return service.reset_weekly_demo()
    except Exception:  # noqa: BLE001 - a housekeeping task must not stop beat
        log.error("synthetic organization demo reset failed unexpectedly", exc_info=True)
        return {
            "status": "failed",
            "project_id": current_app.config.get("DIGITVA_WEEKLY_DEMO_PROJECT_ID", ""),
            "error_code": "unexpected",
        }


def ensure_weekly_demo_reset_scheduled():
    """Seed or disable the weekly reset row according to configuration.

    An empty project id is the safe default. In that state no service method
    is called and any previously seeded row is disabled.
    """
    project_id = (current_app.config.get("DIGITVA_WEEKLY_DEMO_PROJECT_ID") or "").strip()
    if not project_id:
        _disable_existing_schedule()
        return False

    return _seed_weekly_crontab()


def _seed_weekly_crontab():
    """Create or repoint the Sunday 23:00 IST beat row idempotently."""
    try:
        from app import db

        with db.engine.begin() as conn:
            schedule_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_crontabschedule "
                    "WHERE minute = '0' AND hour = '23' AND day_of_week = 'sun' "
                    "AND day_of_month = '*' AND month_of_year = '*' "
                    "AND timezone = :timezone LIMIT 1"
                ),
                {"timezone": WEEKLY_DEMO_TIMEZONE},
            ).scalar()
            if schedule_id is None:
                schedule_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_crontabschedule "
                        "(minute, hour, day_of_week, day_of_month, month_of_year, timezone) "
                        "VALUES ('0', '23', 'sun', '*', '*', :timezone) RETURNING id"
                    ),
                    {"timezone": WEEKLY_DEMO_TIMEZONE},
                ).scalar()

            existing = conn.execute(
                sa.text(
                    "SELECT schedule_id FROM public.celery_periodictask "
                    "WHERE name = :name LIMIT 1"
                ),
                {"name": WEEKLY_DEMO_SCHEDULE_NAME},
            ).scalar()
            if existing is None:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO public.celery_periodictask
                            (name, task, args, kwargs, queue, exchange, routing_key, headers,
                             priority, one_off, enabled, total_run_count, description,
                             discriminator, schedule_id)
                        VALUES
                            (:name, :task, '[]', '{}', NULL, NULL, NULL, '{}',
                             NULL, false, true, 0, '', 'crontabschedule', :schedule_id)
                        """
                    ),
                    {
                        "name": WEEKLY_DEMO_SCHEDULE_NAME,
                        "task": WEEKLY_DEMO_TASK_NAME,
                        "schedule_id": schedule_id,
                    },
                )
            else:
                conn.execute(
                    sa.text(
                        "UPDATE public.celery_periodictask "
                        "SET task = :task, schedule_id = :schedule_id, enabled = true, "
                        "discriminator = 'crontabschedule' WHERE name = :name"
                    ),
                    {
                        "name": WEEKLY_DEMO_SCHEDULE_NAME,
                        "task": WEEKLY_DEMO_TASK_NAME,
                        "schedule_id": schedule_id,
                    },
                )

            conn.execute(
                sa.text(
                    "INSERT INTO public.celery_periodictaskchanged (last_update) "
                    "VALUES (NOW()) ON CONFLICT DO NOTHING"
                )
            )
        log.info("Synthetic organization demo reset schedule seeded: Sunday 23:00 IST.")
        return True
    except Exception as exc:  # noqa: BLE001 - beat startup must remain available
        log.warning("Could not seed synthetic organization demo schedule: %s", exc)
        return False


def _disable_existing_schedule():
    """Disable a previously configured row when the project id is cleared."""
    try:
        from app import db

        with db.engine.begin() as conn:
            changed = conn.execute(
                sa.text(
                    "UPDATE public.celery_periodictask SET enabled = false "
                    "WHERE name = :name AND enabled = true"
                ),
                {"name": WEEKLY_DEMO_SCHEDULE_NAME},
            ).rowcount
            if changed:
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )
    except Exception as exc:  # noqa: BLE001 - no configured schedule is safe
        log.warning("Could not disable synthetic organization demo schedule: %s", exc)
