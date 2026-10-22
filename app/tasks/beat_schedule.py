"""Celery beat schedule of the public demo deployment, seeded at worker and
beat startup (``make_celery``).

The main deployment seeds every periodic task there. With
``PUBLIC_DEMO_ENABLED`` (docs/policy/public-demo.md section 8a) the beat
schedules only the tasks in ``DEMO_BEAT_TASKS``; ODK sync, KPI snapshots,
TLS checks and the other main-only jobs are neither seeded nor left
enabled on a database that had them. The allowlist is by task path, so it
holds whatever a row is named (the coding sweep's name follows its interval).
"""

import logging

import sqlalchemy as sa

from app.tasks.public_demo_tasks import PUBLIC_DEMO_PURGE_TASK_NAME
from app.tasks.security_event_tasks import SIGN_IN_IP_WIPE_TASK_NAME
from app.tasks.web_intake_upload_tasks import UPLOAD_PURGE_TASK_NAME

log = logging.getLogger(__name__)

#: Task path -> why the demo needs it.
DEMO_BEAT_TASKS = {
    PUBLIC_DEMO_PURGE_TASK_NAME:
        "deletes accounts idle 30 days and everything they created (a no-op until PUBLIC_DEMO_PURGE_ENABLED)",
    "app.tasks.sync_tasks.sweep_smartva_pending":
        "queues SmartVA for submissions that have none, so a case reaches coding",
    "app.tasks.sync_tasks.release_stale_coding_allocations_task":
        "releases stale allocations and makes a coded case reviewer-eligible after the recode window",
    UPLOAD_PURGE_TASK_NAME: "removes abandoned interview uploads (disk)",
    "app.tasks.notification_tasks.purge_notifications_task":
        "bounds the notification rows web intake and coding write",
    SIGN_IN_IP_WIPE_TASK_NAME: "removes sign-in IPs after their retention",
    "app.tasks.coding_search_telemetry_tasks.prune_coding_search_telemetry_task":
        "bounds the ICD search telemetry coders write",
    "app.tasks.backup_tasks.run_db_backup":
        "nightly backup of the demo database (owner 2026-10-22), so a purge can be undone",
}


def seed_demo_beat_schedule() -> int:
    """Seed the allowed entries (idempotent) and disable every other enabled
    row; returns the rows disabled. Does nothing, with one logged error, when
    the database holds a project other than the demo's (a demo deployment
    pointed at the main database; policy section 8a)."""
    from app.services import public_demo_service

    if public_demo_service.foreign_projects_exist():
        public_demo_service.log_main_database_refusal()
        return 0
    from app.tasks.backup_tasks import ensure_db_backup_scheduled
    from app.tasks.coding_search_telemetry_tasks import (
        ensure_coding_search_telemetry_prune_scheduled,
    )
    from app.tasks.notification_tasks import ensure_notification_purge_scheduled
    from app.tasks.public_demo_tasks import ensure_public_demo_purge_scheduled
    from app.tasks.security_event_tasks import ensure_sign_in_ip_wipe_scheduled
    from app.tasks.sync_tasks import (
        ensure_coding_timeout_cleanup_scheduled,
        ensure_smartva_sweep_scheduled,
    )
    from app.tasks.web_intake_upload_tasks import ensure_web_intake_upload_purge_scheduled

    ensure_smartva_sweep_scheduled(bundle_applier=False)
    ensure_coding_timeout_cleanup_scheduled()
    ensure_web_intake_upload_purge_scheduled()
    ensure_notification_purge_scheduled()
    ensure_sign_in_ip_wipe_scheduled()
    ensure_coding_search_telemetry_prune_scheduled()
    ensure_db_backup_scheduled()
    ensure_public_demo_purge_scheduled()
    return disable_off_allowlist()


def disable_off_allowlist() -> int:
    """Disable every enabled periodic task whose task path is not in
    ``DEMO_BEAT_TASKS``; returns how many. Rows are kept, not deleted."""
    from app import db
    from app.services import public_demo_service

    if public_demo_service.foreign_projects_exist():
        public_demo_service.log_main_database_refusal()
        return 0
    try:
        with db.engine.begin() as conn:
            disabled = conn.execute(
                sa.text(
                    "UPDATE public.celery_periodictask SET enabled = false "
                    "WHERE enabled AND task NOT IN :allowed"
                ).bindparams(sa.bindparam("allowed", expanding=True)),
                {"allowed": sorted(DEMO_BEAT_TASKS)},
            ).rowcount
            if disabled:
                conn.execute(sa.text(
                    "INSERT INTO public.celery_periodictaskchanged (last_update) "
                    "VALUES (NOW()) ON CONFLICT DO NOTHING"
                ))
    except Exception as exc:  # noqa: BLE001 - startup must not die on the beat tables
        log.warning("Could not disable main-only beat tasks: %s", exc)
        return 0
    log.info("Public demo beat: %d main-only task(s) disabled.", disabled)
    return disabled
