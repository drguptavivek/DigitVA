import json
import logging
import os
from datetime import datetime, timezone

from dateutil import parser
from flask import current_app, jsonify, render_template, request
from flask_login import current_user
import sqlalchemy as sa

from app import db, limiter
from app.decorators import role_required
from app.models import MapProjectSiteOdk, VaSyncRun
from app.routes.admin import _json_error, admin
from app.services.odk_connection_guard_service import serialize_connection_guard_state
from app.services.runtime_form_sync_service import sync_runtime_forms_from_site_mappings

log = logging.getLogger(__name__)


@admin.get("/panels/sync")
@role_required("admin")
def admin_panel_sync():
    return render_template("admin/panels/sync_dashboard.html")


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
    """Mark running sync rows stale when Celery has no active sync tasks."""
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
        schedule_hours = _get_sync_schedule_hours()

        return jsonify(
            {
                "is_running": sync_tasks_present or running is not None,
                "possibly_stale": possibly_stale,
                "current_run": _sync_run_dict(running) if running else None,
                "last_completed": _sync_run_dict(last_completed) if last_completed else None,
                "schedule_hours": schedule_hours,
                "odk_connection_alerts": _odk_connection_alerts(),
                "active_tasks": active_sync_tasks,
                "reserved_tasks": reserved_sync_tasks,
                "active_task_summary": active_sync_task_summary,
                "reserved_task_summary": reserved_sync_task_summary,
            }
        )
    except Exception:
        log.error("admin_sync_status failed", exc_info=True)
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
        log.error("admin_sync_history failed", exc_info=True)
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
        log.error("admin_sync_trigger failed", exc_info=True)
        return _json_error("Failed to trigger sync", 500)


@admin.post("/api/sync/stop")
@role_required("admin")
def admin_sync_stop():
    try:
        celery_app = current_app.extensions.get("celery")
        if celery_app is None:
            return _json_error("Celery is not configured.", 503)

        sync_task_names = _sync_task_names()
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
        log.error("admin_sync_stop failed", exc_info=True)
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

        log.info("Sync schedule updated to every %sh", hours)
        return jsonify({"interval_hours": hours})
    except Exception:
        log.error("admin_sync_schedule failed (hours=%s)", hours, exc_info=True)
        return _json_error("Could not update schedule", 503)


@admin.get("/api/sync/coverage")
@role_required("admin")
def admin_sync_coverage():
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app.models.va_submissions import VaSubmissions
        from app.utils.va_odk.va_odk_04_submissioncount import va_odk_submissioncount

        forms = sync_runtime_forms_from_site_mappings()
        mappings = {
            (mapping.project_id, mapping.site_id): mapping
            for mapping in db.session.scalars(sa.select(MapProjectSiteOdk)).all()
        }
        log.info("admin_sync_coverage: checking %d active runtime forms", len(forms))

        local_data = {}
        for form in forms:
            local_count = (
                db.session.scalar(
                    sa.select(sa.func.count()).where(VaSubmissions.va_form_id == form.form_id)
                )
                or 0
            )
            local_data[(form.project_id, form.site_id)] = {
                "form": form,
                "local_count": local_count,
            }

        flask_app = current_app._get_current_object()

        def fetch_odk_count(form):
            with flask_app.app_context():
                mapping = mappings.get((form.project_id, form.site_id))
                if mapping is None:
                    return form, None, "Active runtime form is missing a site mapping."
                try:
                    count = va_odk_submissioncount(
                        mapping.odk_project_id,
                        mapping.odk_form_id,
                        app_project_id=form.project_id,
                    )
                    log.info("coverage %s/%s: odk=%d", form.project_id, form.site_id, count)
                    return form, count, None
                except Exception:
                    log.warning(
                        "coverage ODK count failed for %s/%s",
                        form.project_id,
                        form.site_id,
                        exc_info=True,
                    )
                    return form, None, "ODK count failed."

        odk_results = {}
        with ThreadPoolExecutor(max_workers=len(forms) or 1) as ex:
            futures = {ex.submit(fetch_odk_count, form): form for form in forms}
            for future in as_completed(futures):
                form, odk_count, odk_error = future.result()
                odk_results[(form.project_id, form.site_id)] = (odk_count, odk_error)

        rows = []
        odk_total = 0
        local_total = 0
        for form in forms:
            key = (form.project_id, form.site_id)
            odk_count, odk_error = odk_results.get(key, (None, "No result"))
            local_count = local_data[key]["local_count"]
            mapping = mappings.get(key)
            if mapping is None:
                continue

            rows.append(
                {
                    "project_id": form.project_id,
                    "site_id": form.site_id,
                    "odk_project_id": mapping.odk_project_id,
                    "odk_form_id": mapping.odk_form_id,
                    "form_id": form.form_id,
                    "can_site_sync": True,
                    "odk_total": odk_count,
                    "local_total": local_count,
                    "missing": (odk_count - local_count) if odk_count is not None else None,
                    "error": odk_error,
                    "last_synced_at": (
                        mapping.last_synced_at.isoformat()
                        if mapping.last_synced_at
                        else None
                    ),
                }
            )
            if odk_count is not None:
                odk_total += odk_count
            local_total += local_count

        log.info(
            "admin_sync_coverage complete: odk_total=%d local_total=%d",
            odk_total,
            local_total,
        )
        return jsonify(
            {
                "mappings": rows,
                "totals": {"odk_total": odk_total, "local_total": local_total},
            }
        )
    except Exception:
        log.error("admin_sync_coverage failed", exc_info=True)
        return _json_error("Failed to load coverage data", 500)


@admin.get("/api/sync/backfill-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_backfill_stats():
    """Return local per-form data, metadata, attachment, and SmartVA completeness counts."""
    try:
        from app.models.va_project_master import VaProjectMaster
        from app.models.va_sites import VaSites
        from app.models.va_smartva_results import VaSmartvaResults
        from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
        from app.models.va_submission_attachments import VaSubmissionAttachments
        from app.models.va_submissions import VaSubmissions

        forms = sync_runtime_forms_from_site_mappings()
        if not forms:
            return jsonify(
                {
                    "projects": [],
                    "totals": {
                        "local_total": 0,
                        "metadata_complete": 0,
                        "attachments_complete": 0,
                        "smartva_complete": 0,
                        "smartva_failed": 0,
                        "smartva_missing": 0,
                        "smartva_no_consent": 0,
                    },
                }
            )

        app_data_root = current_app.config.get("APP_DATA")

        def resolve_attachment_file_path(
            form_id: str,
            local_path: str | None,
            storage_name: str | None,
            *,
            include_audit: bool = False,
        ) -> str | None:
            if storage_name and app_data_root:
                disk_path = os.path.join(app_data_root, form_id, "media", storage_name)
                if os.path.exists(disk_path):
                    return disk_path
            if local_path:
                if os.path.isabs(local_path):
                    if os.path.exists(local_path):
                        return local_path
                elif app_data_root:
                    disk_path = os.path.join(app_data_root, local_path)
                    if os.path.exists(disk_path):
                        return disk_path
            if include_audit and app_data_root and storage_name:
                audit_disk_path = os.path.join(app_data_root, form_id, "media", storage_name)
                if os.path.exists(audit_disk_path):
                    return audit_disk_path
            return None

        attachment_expected_counts = dict(
            db.session.execute(
                sa.select(
                    VaSubmissions.va_sid,
                    sa.func.count(VaSubmissionAttachments.va_sid).label("attachment_count"),
                )
                .select_from(VaSubmissions)
                .join(
                    VaSubmissionAttachments,
                    VaSubmissionAttachments.va_sid == VaSubmissions.va_sid,
                    isouter=True,
                )
                .where(VaSubmissionAttachments.exists_on_odk.is_(True))
                .group_by(VaSubmissions.va_sid)
            ).all()
        )

        local_counts = {}
        submission_rows = db.session.execute(
            sa.select(
                VaSubmissions.va_form_id,
                VaSubmissions.va_sid,
                VaSubmissions.va_consent,
                VaSubmissionPayloadVersion.has_required_metadata,
                VaSubmissionPayloadVersion.attachments_expected,
                VaSmartvaResults.va_smartva_outcome,
                VaSmartvaResults.va_smartva_status,
            )
            .select_from(VaSubmissions)
            .join(
                VaSubmissionPayloadVersion,
                VaSubmissionPayloadVersion.payload_version_id
                == VaSubmissions.active_payload_version_id,
                isouter=True,
            )
            .join(
                VaSmartvaResults,
                sa.and_(
                    VaSmartvaResults.va_sid == VaSubmissions.va_sid,
                    VaSmartvaResults.va_smartva_status.is_not(None),
                ),
                isouter=True,
            )
        ).all()
        for row in submission_rows:
            counts = local_counts.setdefault(
                row.va_form_id,
                {
                    "local_total": 0,
                    "metadata_complete": 0,
                    "attachments_complete": 0,
                    "smartva_complete": 0,
                    "smartva_failed": 0,
                    "smartva_eligible": 0,
                    "smartva_no_consent": 0,
                },
            )
            counts["local_total"] += 1
            if row.has_required_metadata:
                counts["metadata_complete"] += 1

            attachments_expected = row.attachments_expected or 0
            if attachments_expected <= int(attachment_expected_counts.get(row.va_sid) or 0):
                counts["attachments_complete"] += 1

            consent_value = (row.va_consent or "").strip().lower()
            if consent_value == "yes":
                counts["smartva_eligible"] += 1
            else:
                counts["smartva_no_consent"] += 1

            if row.va_smartva_outcome == VaSmartvaResults.OUTCOME_SUCCESS:
                counts["smartva_complete"] += 1
            elif row.va_smartva_outcome == VaSmartvaResults.OUTCOME_FAILED:
                counts["smartva_failed"] += 1

        attachment_rows = db.session.execute(
            sa.select(
                VaSubmissions.va_form_id,
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
                VaSubmissionAttachments.local_path,
                VaSubmissionAttachments.storage_name,
            )
            .select_from(VaSubmissionAttachments)
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        ).all()

        non_audit_attachments_expected_by_form = {}
        non_audit_attachments_present_by_form = {}
        audit_attachments_expected_by_form = {}
        audit_attachments_present_by_form = {}
        legacy_attachment_rows_total_by_form = {}

        for row in attachment_rows:
            is_audit = row.filename == "audit.csv"
            file_path = resolve_attachment_file_path(
                row.va_form_id,
                row.local_path,
                row.storage_name,
                include_audit=is_audit,
            )

            if is_audit:
                if row.storage_name is None:
                    legacy_attachment_rows_total_by_form[row.va_form_id] = (
                        legacy_attachment_rows_total_by_form.get(row.va_form_id, 0) + 1
                    )
                    continue
                audit_attachments_expected_by_form[row.va_form_id] = (
                    audit_attachments_expected_by_form.get(row.va_form_id, 0) + 1
                )
                if file_path:
                    audit_attachments_present_by_form[row.va_form_id] = (
                        audit_attachments_present_by_form.get(row.va_form_id, 0) + 1
                    )
                continue

            non_audit_attachments_expected_by_form[row.va_form_id] = (
                non_audit_attachments_expected_by_form.get(row.va_form_id, 0) + 1
            )
            if file_path:
                non_audit_attachments_present_by_form[row.va_form_id] = (
                    non_audit_attachments_present_by_form.get(row.va_form_id, 0) + 1
                )
            if row.storage_name is None:
                legacy_attachment_rows_total_by_form[row.va_form_id] = (
                    legacy_attachment_rows_total_by_form.get(row.va_form_id, 0) + 1
                )

        projects_map = {}
        total_local = 0
        total_metadata = 0
        total_attachments = 0
        total_non_audit_attachments_expected = 0
        total_non_audit_attachments_present = 0
        total_audit_attachments_expected = 0
        total_audit_attachments_present = 0
        total_legacy_attachment_rows_total = 0
        total_smartva = 0
        total_smartva_failed = 0
        total_smartva_missing = 0
        total_smartva_no_consent = 0

        for form in forms:
            counts = local_counts.get(form.form_id, {})
            local_total = int(counts.get("local_total") or 0)
            metadata_complete = int(counts.get("metadata_complete") or 0)
            attachments_complete = int(counts.get("attachments_complete") or 0)
            non_audit_attachments_expected = int(
                non_audit_attachments_expected_by_form.get(form.form_id) or 0
            )
            non_audit_attachments_present = int(
                non_audit_attachments_present_by_form.get(form.form_id) or 0
            )
            audit_attachments_expected = int(
                audit_attachments_expected_by_form.get(form.form_id) or 0
            )
            audit_attachments_present = int(
                audit_attachments_present_by_form.get(form.form_id) or 0
            )
            legacy_attachment_rows_total = int(
                legacy_attachment_rows_total_by_form.get(form.form_id) or 0
            )
            smartva_complete = int(counts.get("smartva_complete") or 0)
            smartva_failed = int(counts.get("smartva_failed") or 0)
            smartva_eligible = int(counts.get("smartva_eligible") or 0)
            smartva_no_consent = int(counts.get("smartva_no_consent") or 0)
            smartva_missing = max(smartva_eligible - smartva_complete - smartva_failed, 0)

            total_local += local_total
            total_metadata += metadata_complete
            total_attachments += attachments_complete
            total_non_audit_attachments_expected += non_audit_attachments_expected
            total_non_audit_attachments_present += non_audit_attachments_present
            total_audit_attachments_expected += audit_attachments_expected
            total_audit_attachments_present += audit_attachments_present
            total_legacy_attachment_rows_total += legacy_attachment_rows_total
            total_smartva += smartva_complete
            total_smartva_failed += smartva_failed
            total_smartva_missing += smartva_missing
            total_smartva_no_consent += smartva_no_consent

            project = projects_map.setdefault(
                form.project_id,
                {
                    "project_id": form.project_id,
                    "project_name": None,
                    "sites": {},
                    "local_total": 0,
                    "metadata_complete": 0,
                    "attachments_complete": 0,
                    "non_audit_attachments_expected": 0,
                    "non_audit_attachments_present": 0,
                    "audit_attachments_expected": 0,
                    "audit_attachments_present": 0,
                    "legacy_attachment_rows_total": 0,
                    "smartva_complete": 0,
                    "smartva_failed": 0,
                    "smartva_missing": 0,
                    "smartva_no_consent": 0,
                },
            )
            project["local_total"] += local_total
            project["metadata_complete"] += metadata_complete
            project["attachments_complete"] += attachments_complete
            project["non_audit_attachments_expected"] += non_audit_attachments_expected
            project["non_audit_attachments_present"] += non_audit_attachments_present
            project["audit_attachments_expected"] += audit_attachments_expected
            project["audit_attachments_present"] += audit_attachments_present
            project["legacy_attachment_rows_total"] += legacy_attachment_rows_total
            project["smartva_complete"] += smartva_complete
            project["smartva_failed"] += smartva_failed
            project["smartva_missing"] += smartva_missing
            project["smartva_no_consent"] += smartva_no_consent

            site = project["sites"].setdefault(
                form.site_id,
                {
                    "site_id": form.site_id,
                    "site_name": None,
                    "forms": [],
                    "local_total": 0,
                    "metadata_complete": 0,
                    "attachments_complete": 0,
                    "non_audit_attachments_expected": 0,
                    "non_audit_attachments_present": 0,
                    "audit_attachments_expected": 0,
                    "audit_attachments_present": 0,
                    "legacy_attachment_rows_total": 0,
                    "smartva_complete": 0,
                    "smartva_failed": 0,
                    "smartva_missing": 0,
                    "smartva_no_consent": 0,
                },
            )
            site["local_total"] += local_total
            site["metadata_complete"] += metadata_complete
            site["attachments_complete"] += attachments_complete
            site["non_audit_attachments_expected"] += non_audit_attachments_expected
            site["non_audit_attachments_present"] += non_audit_attachments_present
            site["audit_attachments_expected"] += audit_attachments_expected
            site["audit_attachments_present"] += audit_attachments_present
            site["legacy_attachment_rows_total"] += legacy_attachment_rows_total
            site["smartva_complete"] += smartva_complete
            site["smartva_failed"] += smartva_failed
            site["smartva_missing"] += smartva_missing
            site["smartva_no_consent"] += smartva_no_consent
            site["forms"].append(
                {
                    "form_id": form.form_id,
                    "local_total": local_total,
                    "metadata_complete": metadata_complete,
                    "metadata_missing": max(local_total - metadata_complete, 0),
                    "attachments_complete": attachments_complete,
                    "attachments_missing": max(local_total - attachments_complete, 0),
                    "non_audit_attachments_expected": non_audit_attachments_expected,
                    "non_audit_attachments_present": non_audit_attachments_present,
                    "non_audit_attachments_missing": max(
                        non_audit_attachments_expected - non_audit_attachments_present,
                        0,
                    ),
                    "audit_attachments_expected": audit_attachments_expected,
                    "audit_attachments_present": audit_attachments_present,
                    "audit_attachments_missing": max(
                        audit_attachments_expected - audit_attachments_present,
                        0,
                    ),
                    "legacy_attachment_rows_total": legacy_attachment_rows_total,
                    "smartva_complete": smartva_complete,
                    "smartva_failed": smartva_failed,
                    "smartva_missing": smartva_missing,
                    "smartva_no_consent": smartva_no_consent,
                }
            )

        project_names = {
            r.project_id: r.project_name
            for r in db.session.scalars(sa.select(VaProjectMaster)).all()
        }
        site_names = {
            r.site_id: r.site_name for r in db.session.scalars(sa.select(VaSites)).all()
        }
        for pid, project in projects_map.items():
            project["project_name"] = project_names.get(pid, pid)
            for sid, site in project["sites"].items():
                site["site_name"] = site_names.get(sid, sid)
                site["forms"] = sorted(site["forms"], key=lambda item: item["form_id"])
            project["sites"] = sorted(
                project["sites"].values(), key=lambda item: item["site_id"]
            )

        return jsonify(
            {
                "projects": sorted(projects_map.values(), key=lambda item: item["project_id"]),
                "totals": {
                    "local_total": total_local,
                    "metadata_complete": total_metadata,
                    "attachments_complete": total_attachments,
                    "non_audit_attachments_expected": total_non_audit_attachments_expected,
                    "non_audit_attachments_present": total_non_audit_attachments_present,
                    "non_audit_attachments_missing": max(
                        total_non_audit_attachments_expected
                        - total_non_audit_attachments_present,
                        0,
                    ),
                    "audit_attachments_expected": total_audit_attachments_expected,
                    "audit_attachments_present": total_audit_attachments_present,
                    "audit_attachments_missing": max(
                        total_audit_attachments_expected - total_audit_attachments_present,
                        0,
                    ),
                    "legacy_attachment_rows_total": total_legacy_attachment_rows_total,
                    "smartva_complete": total_smartva,
                    "smartva_failed": total_smartva_failed,
                    "smartva_missing": total_smartva_missing,
                    "smartva_no_consent": total_smartva_no_consent,
                },
            }
        )
    except Exception:
        log.error("admin_sync_backfill_stats failed", exc_info=True)
        return _json_error("Failed to load backfill stats", 500)


@admin.get("/api/sync/legacy-attachment-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_legacy_attachment_stats():
    """Return counts for attachment rows missing opaque storage names."""
    try:
        from app.models.va_submission_attachments import VaSubmissionAttachments
        from app.services.attachment_storage_name_service import (
            legacy_attachment_storage_name,
        )

        counts = db.session.execute(
            sa.select(
                sa.func.count().label("total_null_rows"),
                sa.func.count()
                .filter(VaSubmissionAttachments.exists_on_odk.is_(True))
                .label("exists_on_odk_null_rows"),
                sa.func.count()
                .filter(VaSubmissionAttachments.filename == "audit.csv")
                .label("audit_csv_null_rows"),
                sa.func.count()
                .filter(VaSubmissionAttachments.filename != "audit.csv")
                .label("legacy_media_null_rows"),
                sa.func.count()
                .filter(
                    sa.and_(
                        VaSubmissionAttachments.filename != "audit.csv",
                        VaSubmissionAttachments.exists_on_odk.is_(True),
                    )
                )
                .label("legacy_media_exists_on_odk_null_rows"),
            )
            .select_from(VaSubmissionAttachments)
            .where(VaSubmissionAttachments.storage_name.is_(None))
        ).mappings().one()

        repaired_legacy_media_rows = 0
        repaired_rows = db.session.execute(
            sa.select(
                VaSubmissionAttachments.va_sid,
                VaSubmissionAttachments.filename,
                VaSubmissionAttachments.storage_name,
            )
            .where(VaSubmissionAttachments.storage_name.is_not(None))
            .where(VaSubmissionAttachments.filename != "audit.csv")
            .execution_options(yield_per=1000)
        )
        for row in repaired_rows:
            expected_storage_name = legacy_attachment_storage_name(row.va_sid, row.filename)
            if row.storage_name == expected_storage_name:
                repaired_legacy_media_rows += 1

        return jsonify(
            {
                "total_null_rows": int(counts["total_null_rows"] or 0),
                "exists_on_odk_null_rows": int(counts["exists_on_odk_null_rows"] or 0),
                "audit_csv_null_rows": int(counts["audit_csv_null_rows"] or 0),
                "legacy_media_null_rows": int(counts["legacy_media_null_rows"] or 0),
                "legacy_media_exists_on_odk_null_rows": int(
                    counts["legacy_media_exists_on_odk_null_rows"] or 0
                ),
                "repaired_legacy_media_rows": repaired_legacy_media_rows,
            }
        )
    except Exception:
        log.error("admin_sync_legacy_attachment_stats failed", exc_info=True)
        return _json_error("Failed to load legacy attachment stats", 500)


@admin.post("/api/sync/backfill/form/<form_id>")
@role_required("admin")
def admin_sync_backfill_form(form_id: str):
    """Repair local sync gaps for a single form without force-resyncing it."""
    try:
        from app.models.va_forms import VaForms
        from app.tasks.sync_tasks import run_single_form_backfill

        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            return _json_error(f"Form '{form_id}' not found.", 404)

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun).where(VaSyncRun.status == "running").limit(1)
        )
        if running:
            return _json_error("A sync is already in progress.", 409)

        task = run_single_form_backfill.delay(
            form_id=form_id,
            triggered_by="backfill",
            user_id=str(current_user.user_id),
        )
        return (
            jsonify(
                {
                    "message": f"Repair started for form {form_id}.",
                    "task_id": task.id,
                    "form_id": form_id,
                }
            ),
            202,
        )
    except Exception:
        log.error("admin_sync_backfill_form failed for %s", form_id, exc_info=True)
        return _json_error(f"Failed to trigger repair for form {form_id}", 500)


@admin.post("/api/sync/legacy-attachment-repair")
@role_required("admin")
def admin_sync_legacy_attachment_repair():
    """Populate storage_name for legacy media attachment rows."""
    try:
        from app.tasks.sync_tasks import run_legacy_attachment_repair

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun).where(VaSyncRun.status == "running").limit(1)
        )
        if running:
            return _json_error("A sync is already in progress.", 409)

        task = run_legacy_attachment_repair.delay(
            triggered_by="legacy-repair",
            user_id=str(current_user.user_id),
        )
        return jsonify(
            {
                "message": "Legacy attachment repair started.",
                "task_id": task.id,
            }
        ), 202
    except Exception:
        log.error("admin_sync_legacy_attachment_repair failed", exc_info=True)
        return _json_error("Failed to trigger legacy attachment repair", 500)


@admin.post("/api/sync/form/<form_id>")
@role_required("admin")
def admin_sync_form(form_id: str):
    """Force-resync a single form, bypassing the delta check."""
    try:
        from app.models.va_forms import VaForms
        from app.services.runtime_form_sync_service import get_active_mapping_for_form
        from app.tasks.sync_tasks import run_single_form_sync

        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            return _json_error(f"Form '{form_id}' not found.", 404)
        if get_active_mapping_for_form(va_form) is None:
            return _json_error(
                f"Active runtime mapping not found for form '{form_id}'.",
                404,
            )

        _reconcile_orphaned_running_sync_rows()
        log.info(
            "Single-form force-resync of %s triggered by user %s",
            form_id,
            current_user.user_id,
        )
        task = run_single_form_sync.delay(
            form_id=form_id,
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return (
            jsonify(
                {
                    "message": f"Force-resync started for form {form_id}.",
                    "task_id": task.id,
                }
            ),
            202,
        )
    except Exception:
        log.error("admin_sync_form failed for %s", form_id, exc_info=True)
        return _json_error(f"Failed to trigger Force-resync for form {form_id}", 500)


@admin.post("/api/sync/project-site/<project_id>/<site_id>")
@role_required("admin")
def admin_sync_project_site(project_id: str, site_id: str):
    """Materialize the runtime form for one mapping and trigger a form sync."""
    try:
        from app.services.runtime_form_sync_service import (
            ensure_runtime_form_for_mapping,
            sync_runtime_forms_from_site_mappings,
        )
        from app.tasks.sync_tasks import run_single_form_sync

        active_form = next(
            (
                form
                for form in sync_runtime_forms_from_site_mappings()
                if form.project_id == project_id and form.site_id == site_id
            ),
            None,
        )
        if active_form is None:
            return _json_error(
                f"Active runtime mapping not found for project/site '{project_id}/{site_id}'.",
                404,
            )

        mapping = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == project_id,
                MapProjectSiteOdk.site_id == site_id,
            )
        )
        if mapping is None:
            return _json_error(
                f"ODK mapping not found for project/site '{project_id}/{site_id}'.",
                404,
            )

        va_form = ensure_runtime_form_for_mapping(mapping)
        db.session.commit()

        log.info(
            "Project/site sync of %s/%s (%s) triggered by user %s",
            project_id,
            site_id,
            va_form.form_id,
            current_user.user_id,
        )
        task = run_single_form_sync.delay(
            form_id=va_form.form_id,
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return (
            jsonify(
                {
                    "message": (
                        f"Sync started for {project_id}/{site_id} "
                        f"using form {va_form.form_id}."
                    ),
                    "task_id": task.id,
                    "form_id": va_form.form_id,
                }
            ),
            202,
        )
    except Exception:
        log.error(
            "admin_sync_project_site failed for %s/%s",
            project_id,
            site_id,
            exc_info=True,
        )
        return _json_error(
            f"Failed to trigger sync for project/site {project_id}/{site_id}.",
            500,
        )


@admin.get("/api/sync/revoked-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_revoked_stats():
    """Return counts of submissions in finalized_upstream_changed state."""
    try:
        from app.models.va_forms import VaForms
        from app.models.va_project_master import VaProjectMaster
        from app.models.va_sites import VaSites
        from app.models.va_submission_workflow import VaSubmissionWorkflow
        from app.models.va_submissions import VaSubmissions
        from app.services.workflow.definition import WORKFLOW_FINALIZED_UPSTREAM_CHANGED

        revoked_by_form = dict(
            db.session.execute(
                sa.select(
                    VaSubmissions.va_form_id,
                    sa.func.count(VaSubmissions.va_sid).label("cnt"),
                )
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(
                    VaSubmissionWorkflow.workflow_state
                    == WORKFLOW_FINALIZED_UPSTREAM_CHANGED
                )
                .group_by(VaSubmissions.va_form_id)
            ).all()
        )

        if not revoked_by_form:
            return jsonify({"projects": [], "totals": {"revoked": 0}})

        forms = db.session.scalars(
            sa.select(VaForms).where(VaForms.form_id.in_(revoked_by_form.keys()))
        ).all()

        projects_map = {}
        total_revoked = 0

        for form in forms:
            revoked_count = revoked_by_form.get(form.form_id, 0)
            if revoked_count == 0:
                continue

            total_revoked += revoked_count

            proj = projects_map.setdefault(
                form.project_id,
                {
                    "project_id": form.project_id,
                    "project_name": None,
                    "sites": {},
                    "revoked": 0,
                },
            )
            proj["revoked"] += revoked_count

            site = proj["sites"].setdefault(
                form.site_id,
                {
                    "site_id": form.site_id,
                    "site_name": None,
                    "forms": {},
                    "revoked": 0,
                },
            )
            site["revoked"] += revoked_count

            site["forms"][form.form_id] = {
                "form_id": form.form_id,
                "revoked": revoked_count,
            }

        project_names = {
            r.project_id: r.project_name
            for r in db.session.scalars(sa.select(VaProjectMaster)).all()
        }
        site_names = {
            r.site_id: r.site_name for r in db.session.scalars(sa.select(VaSites)).all()
        }
        for pid, proj in projects_map.items():
            proj["project_name"] = project_names.get(pid, pid)
            for sid, site in proj["sites"].items():
                site["site_name"] = site_names.get(sid, sid)
            proj["sites"] = list(proj["sites"].values())

        return jsonify(
            {
                "projects": list(projects_map.values()),
                "totals": {"revoked": total_revoked},
            }
        )
    except Exception:
        log.error("admin_sync_revoked_stats failed", exc_info=True)
        return _json_error("Failed to load revoked stats", 500)


@admin.get("/api/sync/progress")
@limiter.exempt
@role_required("admin")
def admin_sync_progress():
    """Return live progress log for the currently running sync, or the last run."""
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
                entries = json.loads(run.progress_log)
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
        log.error("admin_sync_progress failed", exc_info=True)
        return _json_error("Failed to load progress", 500)


def _sync_run_dict(run) -> dict:
    """Serialise a VaSyncRun to a JSON-safe dict."""
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
    """Return the configured sync interval in hours, or None if not set."""
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
    """Return active ODK connection alerts for operator-facing admin panels."""
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
