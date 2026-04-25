import json
import logging
from datetime import datetime, timezone

from dateutil import parser
from flask import current_app
import sqlalchemy as sa

from app import db
from app.models import MapProjectSiteOdk, VaSyncRun
from app.services.odk.connection_guard import serialize_connection_guard_state

log = logging.getLogger(__name__)


def _sync_task_names() -> set[str]:
    return {
        "app.tasks.sync_tasks.run_odk_sync",
        "app.tasks.sync_tasks.run_single_form_sync",
        "app.tasks.sync_tasks.run_single_form_backfill",
        "app.tasks.sync_tasks.run_single_submission_sync",
        "app.tasks.sync_tasks.run_canonical_repair_batches_task",
        "app.tasks.sync_tasks.finalize_canonical_repair_run_task",
        "app.tasks.sync_tasks.run_legacy_attachment_repair",
    }


def _sync_dashboard_triggered_by_values() -> tuple[str, ...]:
    return ("scheduled", "manual", "backfill", "legacy-repair")


def _sync_dashboard_runs_query():
    return sa.select(VaSyncRun).where(
        VaSyncRun.triggered_by.in_(_sync_dashboard_triggered_by_values())
    )


def _extract_sync_task_info(*, worker: str, task: dict, state: str) -> dict:
    kwargs = task.get("kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}
    return {
        "worker": worker,
        "id": task.get("id"),
        "name": task.get("name"),
        "state": state,
        "run_id": kwargs.get("run_id"),
        "form_id": kwargs.get("form_id"),
        "label": kwargs.get("label"),
    }


def _sync_task_snapshot(*, timeout: float = 0.5) -> dict[str, list[dict]]:
    celery_app = current_app.extensions.get("celery")
    if celery_app is None:
        return {"active": [], "reserved": []}

    inspect = celery_app.control.inspect(timeout=timeout)
    sync_task_names = _sync_task_names()
    snapshot: dict[str, list[dict]] = {"active": [], "reserved": []}

    for state in ("active", "reserved"):
        state_fetcher = getattr(inspect, state, None)
        if state_fetcher is None:
            continue
        tasks_by_worker = state_fetcher() or {}
        tasks = []
        for worker, worker_tasks in tasks_by_worker.items():
            for task in (worker_tasks or []):
                if task.get("name") in sync_task_names:
                    tasks.append(
                        _extract_sync_task_info(worker=worker, task=task, state=state)
                    )
        snapshot[state] = tasks
    return snapshot


def _active_sync_tasks() -> list[dict]:
    return _sync_task_snapshot().get("active", [])


def _reserved_sync_tasks() -> list[dict]:
    return _sync_task_snapshot().get("reserved", [])


def _summarize_active_sync_tasks(tasks: list[dict]) -> dict:
    coordinator_names = {
        "app.tasks.sync_tasks.run_odk_sync",
        "app.tasks.sync_tasks.run_single_form_sync",
        "app.tasks.sync_tasks.run_single_form_backfill",
        "app.tasks.sync_tasks.run_single_submission_sync",
        "app.tasks.sync_tasks.run_legacy_attachment_repair",
    }
    finalizer_name = "app.tasks.sync_tasks.finalize_canonical_repair_run_task"
    repair_name = "app.tasks.sync_tasks.run_canonical_repair_batches_task"

    coordinators = [task for task in tasks if task.get("name") in coordinator_names]
    repair_batches = [task for task in tasks if task.get("name") == repair_name]
    finalizers = [task for task in tasks if task.get("name") == finalizer_name]

    return {
        "coordinator_count": len(coordinators),
        "repair_batch_count": len(repair_batches),
        "finalizer_count": len(finalizers),
        "coordinator_tasks": coordinators,
        "repair_batch_tasks": repair_batches,
        "finalizer_tasks": finalizers,
    }


def _sync_run_last_progress_at(run) -> datetime | None:
    progress_log = run.progress_log
    if not progress_log:
        return None
    try:
        entries = json.loads(progress_log)
    except Exception:
        return None
    if not isinstance(entries, list) or not entries:
        return None
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        ts = entry.get("ts")
        if not ts:
            continue
        try:
            return parser.isoparse(ts)
        except Exception:
            continue
    return None


def _is_interrupted_sync_error(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return (
        "no active celery sync/backfill task was found" in lowered
        or "worker stopped before completion" in lowered
        or "worker likely restarted before completion" in lowered
        or "interrupted run" in lowered
    )


def _reconcile_orphaned_running_sync_rows(
    task_snapshot: dict[str, list[dict]] | None = None,
) -> None:
    from datetime import timedelta

    running_rows = db.session.scalars(
        sa.select(VaSyncRun)
        .where(VaSyncRun.status == "running")
        .order_by(VaSyncRun.started_at.desc())
    ).all()
    if not running_rows:
        return

    task_snapshot = task_snapshot or _sync_task_snapshot()
    active_sync_task_found = bool(task_snapshot.get("active") or task_snapshot.get("reserved"))
    if active_sync_task_found and not running_rows:
        recent_row = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "error")
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )
        if recent_row is not None:
            last_progress_at = _sync_run_last_progress_at(recent_row)
            now = datetime.now(timezone.utc)
            if (
                recent_row.started_at
                and recent_row.started_at > now - timedelta(minutes=10)
                and last_progress_at
                and last_progress_at > now - timedelta(minutes=3)
                and recent_row.error_message
                and _is_interrupted_sync_error(recent_row.error_message)
            ):
                recent_row.status = "running"
                recent_row.finished_at = None
                recent_row.error_message = None
                db.session.commit()
        return
    if active_sync_task_found:
        return

    now = datetime.now(timezone.utc)
    reconciled = 0
    for row in running_rows:
        last_progress_at = _sync_run_last_progress_at(row)
        if last_progress_at and last_progress_at > now - timedelta(minutes=3):
            continue
        row.status = "error"
        row.finished_at = now
        row.error_message = (
            "Stale run — no active Celery sync/backfill task was found and no recent progress was recorded. "
            "Re-initiate Sync or Repair to continue remaining gaps."
        )
        reconciled += 1
    if reconciled:
        db.session.commit()
        log.warning(
            "Reconciled %d orphaned running sync row(s) with no active Celery task.",
            reconciled,
        )
    else:
        db.session.rollback()


def _sync_run_dict(run) -> dict:
    if run is None:
        return None
    duration = None
    if run.finished_at and run.started_at:
        duration = int((run.finished_at - run.started_at).total_seconds())
    return {
        "sync_run_id": str(run.sync_run_id),
        "triggered_by": run.triggered_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": duration,
        "status": run.status,
        "records_added": run.records_added,
        "records_updated": run.records_updated,
        "error_message": run.error_message,
    }


def _get_sync_schedule_hours() -> int | None:
    try:
        with db.engine.connect() as conn:
            tables_ready = conn.execute(
                sa.text(
                    """
                SELECT
                    to_regclass('public.celery_periodictask') IS NOT NULL
                    AND to_regclass('public.celery_intervalschedule') IS NOT NULL
            """
                )
            ).scalar()
            if not tables_ready:
                return None
            row = conn.execute(
                sa.text(
                    """
                SELECT i.every
                FROM public.celery_periodictask t
                JOIN public.celery_intervalschedule i ON i.id = t.schedule_id
                WHERE t.name = 'ODK Sync — every 6 hours'
                  AND t.discriminator = 'intervalschedule'
                LIMIT 1
            """
                )
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None


def _odk_connection_alerts() -> list[dict]:
    from app.models import MasOdkConnections, VaStatuses

    now = datetime.now(timezone.utc)
    conns = db.session.scalars(
        sa.select(MasOdkConnections)
        .where(MasOdkConnections.status == VaStatuses.active)
        .order_by(MasOdkConnections.connection_name)
    ).all()

    alerts = []
    for conn in conns:
        guard = serialize_connection_guard_state(conn)
        if not (guard["cooldown_active"] or guard["consecutive_failure_count"] > 0):
            continue
        alerts.append(
            {
                "connection_id": str(conn.connection_id),
                "connection_name": conn.connection_name,
                "base_url": conn.base_url,
                "guard": guard,
                "cooldown_remaining_seconds": (
                    max(0, int((conn.cooldown_until - now).total_seconds()))
                    if conn.cooldown_until and conn.cooldown_until > now
                    else 0
                ),
            }
        )
    return alerts


def get_all_project_site_mappings():
    return db.session.scalars(sa.select(MapProjectSiteOdk)).all()
