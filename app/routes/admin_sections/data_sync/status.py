from datetime import datetime, timezone

from flask import current_app, jsonify, request
from flask_login import current_user
import sqlalchemy as sa

from app import db, limiter
from app.decorators import role_required
from app.models import VaSyncRun
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.routes.admin_sections import data_sync as sync_routes
from .helpers import (
    _active_sync_tasks,
    _reconcile_orphaned_running_sync_rows,
    _reserved_sync_tasks,
    _summarize_active_sync_tasks,
    _sync_dashboard_runs_query,
    _sync_run_dict,
    _sync_task_snapshot,
)


@admin.get("/api/sync/status")
@limiter.exempt
@role_required("admin")
def admin_sync_status():
    try:
        task_snapshot = _sync_task_snapshot()
        _reconcile_orphaned_running_sync_rows(task_snapshot)
        running = db.session.scalar(
            _sync_dashboard_runs_query()
            .where(VaSyncRun.status == "running")
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )
        active_sync_tasks = task_snapshot.get("active", [])
        reserved_sync_tasks = task_snapshot.get("reserved", [])
        active_sync_task_summary = _summarize_active_sync_tasks(active_sync_tasks)
        reserved_sync_task_summary = _summarize_active_sync_tasks(reserved_sync_tasks)
        sync_tasks_present = bool(active_sync_tasks or reserved_sync_tasks)
        if running is None and sync_tasks_present:
            task_run_ids = [
                task.get("run_id")
                for task in active_sync_tasks + reserved_sync_tasks
                if task.get("run_id")
            ]
            if task_run_ids:
                running = db.session.scalar(
                    _sync_dashboard_runs_query()
                    .where(VaSyncRun.sync_run_id.in_(task_run_ids))
                    .order_by(VaSyncRun.started_at.desc())
                    .limit(1)
                )
            if running is None:
                running = db.session.scalar(
                    _sync_dashboard_runs_query()
                    .order_by(VaSyncRun.started_at.desc())
                    .limit(1)
                )

        possibly_stale = False
        if running:
            age_seconds = (datetime.now(timezone.utc) - running.started_at).total_seconds()
            has_progress = bool(
                running.progress_log and running.progress_log.strip() not in ("", "[]")
            )
            if age_seconds > 600 and not has_progress:
                possibly_stale = True

        last_completed = db.session.scalar(
            _sync_dashboard_runs_query()
            .where(VaSyncRun.status.in_(["success", "partial", "error", "cancelled"]))
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )
        schedule_hours = sync_routes._get_sync_schedule_hours()

        return jsonify(
            {
                "is_running": sync_tasks_present or running is not None,
                "possibly_stale": possibly_stale,
                "current_run": _sync_run_dict(running) if running else None,
                "last_completed": _sync_run_dict(last_completed) if last_completed else None,
                "schedule_hours": schedule_hours,
                "odk_connection_alerts": sync_routes._odk_connection_alerts(),
                "active_tasks": active_sync_tasks,
                "reserved_tasks": reserved_sync_tasks,
                "active_task_summary": active_sync_task_summary,
                "reserved_task_summary": reserved_sync_task_summary,
            }
        )
    except Exception:
        return _json_error("Failed to load sync status", 500)


@admin.get("/api/sync/history")
@limiter.exempt
@role_required("admin")
def admin_sync_history():
    try:
        try:
            limit = min(int(request.args.get("limit", 20)), 100)
        except (TypeError, ValueError):
            limit = 20

        runs = db.session.scalars(
            _sync_dashboard_runs_query().order_by(VaSyncRun.started_at.desc()).limit(limit)
        ).all()
        return jsonify({"runs": [_sync_run_dict(r) for r in runs]})
    except Exception:
        return _json_error("Failed to load sync history", 500)


@admin.post("/api/sync/trigger")
@role_required("admin")
def admin_sync_trigger():
    try:
        from app.tasks.sync_tasks import run_odk_sync

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun).where(VaSyncRun.status == "running").limit(1)
        )
        if running:
            return _json_error(
                "A Sync, Force-resync, or Repair run is already in progress.",
                409,
            )

        task = run_odk_sync.delay(
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": "Sync started.", "task_id": task.id}), 202
    except Exception:
        return _json_error("Failed to trigger sync", 500)


@admin.post("/api/sync/stop")
@role_required("admin")
def admin_sync_stop():
    try:
        celery_app = current_app.extensions.get("celery")
        if celery_app is None:
            return _json_error("Celery is not configured.", 503)

        sync_task_names = sync_routes._sync_task_names()
        task_ids = []
        for task in _active_sync_tasks() + _reserved_sync_tasks():
            if task.get("name") in sync_task_names and task.get("id"):
                task_ids.append(task["id"])
        task_ids = list(dict.fromkeys(task_ids))

        running_rows = db.session.scalars(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .order_by(VaSyncRun.started_at.desc())
        ).all()

        if not task_ids and not running_rows:
            return _json_error("No sync task is currently running.", 409)

        for task_id in task_ids:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

        now = datetime.now(timezone.utc)
        for row in running_rows:
            row.status = "cancelled"
            row.finished_at = now
            row.error_message = "Cancelled by admin."
        db.session.commit()

        return jsonify(
            {
                "message": "Stop signal sent to running sync task(s).",
                "task_ids": task_ids,
                "runs_cancelled": len(running_rows),
            }
        )
    except Exception:
        return _json_error("Failed to stop sync", 500)


@admin.post("/api/sync/schedule")
@role_required("admin")
def admin_sync_schedule():
    data = request.get_json(silent=True) or {}
    try:
        hours = int(data.get("interval_hours", 0))
    except (TypeError, ValueError):
        return _json_error("interval_hours must be an integer.", 400)
    if not (1 <= hours <= 168):
        return _json_error("interval_hours must be between 1 and 168.", 400)

    try:
        with db.engine.begin() as conn:
            tables_ready = conn.execute(
                sa.text(
                    """
                SELECT
                    to_regclass('public.celery_periodictask') IS NOT NULL
                    AND to_regclass('public.celery_intervalschedule') IS NOT NULL
                    AND to_regclass('public.celery_periodictaskchanged') IS NOT NULL
            """
                )
            ).scalar()
            if not tables_ready:
                return _json_error(
                    "Celery Beat schedule tables are not initialized yet.",
                    503,
                )
            interval_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_intervalschedule "
                    "WHERE every = :h AND period = 'hours' LIMIT 1"
                ),
                {"h": hours},
            ).scalar()
            if interval_id is None:
                interval_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_intervalschedule (every, period) "
                        "VALUES (:h, 'hours') RETURNING id"
                    ),
                    {"h": hours},
                ).scalar()

            conn.execute(
                sa.text(
                    """
                UPDATE public.celery_periodictask
                SET schedule_id = :sid,
                    discriminator = 'intervalschedule',
                    date_changed = NOW()
                WHERE name = :name
            """
                ),
                {"sid": interval_id, "name": "ODK Sync — every 6 hours"},
            )

            conn.execute(
                sa.text(
                    "INSERT INTO public.celery_periodictaskchanged (last_update) "
                    "VALUES (NOW()) ON CONFLICT DO NOTHING"
                )
            )

        return jsonify({"interval_hours": hours})
    except Exception:
        return _json_error("Could not update schedule", 503)


@admin.get("/api/sync/progress")
@limiter.exempt
@role_required("admin")
def admin_sync_progress():
    try:
        run = db.session.scalar(
            _sync_dashboard_runs_query()
            .where(VaSyncRun.status == "running")
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )
        if run is None:
            task_run_ids = [
                task.get("run_id")
                for task in _active_sync_tasks() + _reserved_sync_tasks()
                if task.get("run_id")
            ]
            if task_run_ids:
                run = db.session.scalar(
                    _sync_dashboard_runs_query()
                    .where(VaSyncRun.sync_run_id.in_(task_run_ids))
                    .order_by(VaSyncRun.started_at.desc())
                    .limit(1)
                )
        if not run:
            run = db.session.scalar(
                _sync_dashboard_runs_query()
                .order_by(VaSyncRun.started_at.desc())
                .limit(1)
            )

        if not run:
            return jsonify({"is_running": False, "entries": []})

        entries = []
        if run.progress_log:
            try:
                entries = __import__("json").loads(run.progress_log)
            except Exception:
                entries = []

        return jsonify(
            {
                "is_running": run.status == "running",
                "run_id": str(run.sync_run_id),
                "triggered_by": run.triggered_by,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "status": run.status,
                "entries": entries,
            }
        )
    except Exception:
        return _json_error("Failed to load progress", 500)
