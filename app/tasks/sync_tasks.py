"""Celery tasks for ODK data sync.

The run_odk_sync task wraps va_data_sync_odkcentral(), recording every run
in va_sync_runs so the admin dashboard can show history and current status.
"""
import json
import logging
import os
import traceback
import sqlalchemy as sa
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from datetime import datetime, timezone

log = get_task_logger(__name__)
ANALYTICS_MV_TRIGGER = "analytics_mv"
ENRICHMENT_SYNC_BATCH_SIZE = 10
ATTACHMENT_SYNC_BATCH_SIZE = 10


def _normalize_batch_plan(batch_map: dict | None) -> dict[str, dict]:
    """Normalize legacy and stage-aware batch payloads into one shape."""
    normalized: dict[str, dict] = {}
    for va_sid, value in (batch_map or {}).items():
        if isinstance(value, dict):
            normalized[va_sid] = {
                "instance_id": value.get("instance_id") or value.get("KEY") or "",
                "needs_metadata": bool(value.get("needs_metadata")),
                "needs_attachments": bool(value.get("needs_attachments")),
                "needs_smartva": bool(value.get("needs_smartva")),
            }
        else:
            normalized[va_sid] = {
                "instance_id": value or "",
                "needs_metadata": True,
                "needs_attachments": True,
                "needs_smartva": True,
            }
    return normalized


def _batch_stage_counts(batch_plan: dict[str, dict]) -> dict[str, int]:
    """Return counts of submissions needing each stage in a batch plan."""
    return {
        "metadata": sum(1 for item in batch_plan.values() if item.get("needs_metadata")),
        "attachments": sum(1 for item in batch_plan.values() if item.get("needs_attachments")),
        "smartva": sum(1 for item in batch_plan.values() if item.get("needs_smartva")),
    }


def _resolve_present_attachment_file_path(
    *,
    app_data_root: str | None,
    form_id: str,
    local_path: str | None,
    storage_name: str | None,
) -> str | None:
    """Return a real attachment file path if the local blob exists.

    Preference order:
      1. storage_name under APP_DATA/<form_id>/media/
      2. legacy local_path fallback

    Shared artifacts like audit.csv are not treated as attachment blobs.
    """
    if storage_name and app_data_root:
        disk_path = os.path.join(app_data_root, form_id, "media", storage_name)
        if os.path.exists(disk_path):
            return os.path.abspath(disk_path)
    if local_path and os.path.exists(local_path):
        if os.path.basename(local_path).lower() == "audit.csv":
            return None
        return os.path.abspath(local_path)
    return None


def _present_attachment_files_by_submission(
    form_id: str,
    *,
    target_sids: list[str] | None = None,
) -> dict[str, set[str]]:
    """Return deduplicated local attachment file paths per submission."""
    from flask import current_app
    from app import db
    from app.models import VaSubmissions, VaSubmissionAttachments

    app_data_root = current_app.config.get("APP_DATA")
    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.storage_name,
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == form_id,
            VaSubmissionAttachments.exists_on_odk.is_(True),
        )
    )
    if target_sids:
        stmt = stmt.where(VaSubmissionAttachments.va_sid.in_(target_sids))

    present_files_by_sid: dict[str, set[str]] = {}
    for row in db.session.execute(stmt).mappings().all():
        resolved_path = _resolve_present_attachment_file_path(
            app_data_root=app_data_root,
            form_id=form_id,
            local_path=row["local_path"],
            storage_name=row["storage_name"],
        )
        if not resolved_path:
            continue
        present_files_by_sid.setdefault(row["va_sid"], set()).add(resolved_path)
    return present_files_by_sid


def _dispatch_repair_batch(
    *,
    form_id: str,
    batch_map: dict[str, dict] | dict[str, str],
    remaining_batches: list[dict] | None,
    run_id: str,
    batch_index: int,
    batch_total: int,
):
    """Dispatch the next needed stage for a batch."""
    batch_plan = _normalize_batch_plan(batch_map)
    stage_counts = _batch_stage_counts(batch_plan)
    if stage_counts["metadata"] > 0:
        run_enrichment_sync_batch.delay(
            form_id=form_id,
            batch_map=batch_plan,
            remaining_batches=remaining_batches or [],
            run_id=run_id,
            batch_index=batch_index,
            batch_total=batch_total,
        )
        return "enrich"
    if stage_counts["attachments"] > 0:
        run_attachment_sync_batch.delay(
            form_id=form_id,
            batch_map=batch_plan,
            remaining_batches=remaining_batches or [],
            run_id=run_id,
            batch_index=batch_index,
            batch_total=batch_total,
        )
        return "attachments"
    if stage_counts["smartva"] > 0:
        run_smartva_sync_batch.delay(
            form_id=form_id,
            batch_map=batch_plan,
            remaining_batches=remaining_batches or [],
            run_id=run_id,
            batch_index=batch_index,
            batch_total=batch_total,
        )
        return "smartva"
    return None


def _get_single_form_odk_client(va_form):
    """Return one pyODK client for the single-form sync run."""
    from app.utils import va_odk_clientsetup

    return va_odk_clientsetup(project_id=va_form.project_id)


def _release_read_transaction(*entities) -> None:
    """Detach loaded rows and end the current read transaction before remote I/O."""
    from app import db

    for entity in entities:
        if entity is None:
            continue
        try:
            db.session.expunge(entity)
        except Exception:
            log.debug("_release_read_transaction: expunge failed for %r", entity, exc_info=True)
            continue
    db.session.rollback()


def _log_progress(db, run_id, msg: str):
    """Append a timestamped progress entry to va_sync_runs.progress_log.

    Uses a dedicated connection (outside the ORM session) so that a failure
    here never rolls back in-flight sync work.
    """
    try:
        entry = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "msg": msg})
        with db.engine.connect() as conn:
            conn.execute(
                sa.text(
                    "UPDATE va_sync_runs "
                    "SET progress_log = ("
                    "  COALESCE(progress_log::jsonb, '[]'::jsonb) || (:entry)::jsonb"
                    ")::text "
                    "WHERE sync_run_id = :run_id"
                ),
                {"entry": f"[{entry}]", "run_id": str(run_id)},
            )
            conn.commit()
    except Exception:
        log.warning("_log_progress failed for run %s", run_id, exc_info=True)


def _log_progress_exc(db, run_id, label: str, exc: BaseException):
    """Log an exception's full traceback to progress_log so it's dashboard-visible.

    Writes two entries: a short summary line followed by the traceback block.
    Falls back silently — never raises.
    """
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _log_progress(db, run_id, f"ERROR [{label}]: {exc}")
    _log_progress(db, run_id, f"TRACEBACK:\n{tb[:3000]}")


def _get_request_user(user_id):
    from app import db
    from app.models import VaUsers

    if not user_id:
        return None
    return db.session.get(VaUsers, user_id)


def _authorize_data_manager_form_sync(user_id, va_form):
    user = _get_request_user(user_id)
    if user is None:
        return
    if user.is_admin():
        return
    if not user.is_data_manager():
        raise PermissionError("User is not allowed to run data-manager sync.")
    if not user.has_data_manager_submission_access(va_form.project_id, va_form.site_id):
        raise PermissionError("User does not have access to this form.")


def _authorize_data_manager_submission_sync(user_id, submission, va_form):
    user = _get_request_user(user_id)
    if user is None:
        return
    if user.is_admin():
        return
    if not user.is_data_manager():
        raise PermissionError("User is not allowed to run data-manager sync.")
    if not user.has_data_manager_submission_access(va_form.project_id, va_form.site_id):
        raise PermissionError("User does not have access to this submission.")


def _sync_run_in_progress():
    from app import db
    from app.models import VaSyncRun

    return db.session.scalar(
        sa.select(VaSyncRun.sync_run_id)
        .where(VaSyncRun.status == "running")
        .limit(1)
    )


def _append_run_error(run, message: str) -> None:
    if not message:
        return
    if run.error_message:
        if message in run.error_message:
            return
        run.error_message = f"{run.error_message}\n{message}"[:2000]
    else:
        run.error_message = message[:2000]


def _schedule_attachment_sync_for_form(
    run_id,
    form_id: str,
    upserted_map: dict[str, str],
    log_progress,
) -> int:
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    items = list(upserted_map.items())
    batches = [
        dict(items[i:i + ATTACHMENT_SYNC_BATCH_SIZE])
        for i in range(0, len(items), ATTACHMENT_SYNC_BATCH_SIZE)
    ]
    if not batches:
        return 0

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == run_id).with_for_update()
    ).scalar_one()
    run.attachment_forms_total = (run.attachment_forms_total or 0) + len(batches)
    if run.attachment_forms_completed is None:
        run.attachment_forms_completed = 0
    if run.attachment_downloaded is None:
        run.attachment_downloaded = 0
    if run.attachment_skipped is None:
        run.attachment_skipped = 0
    if run.attachment_errors is None:
        run.attachment_errors = 0
    if run.smartva_records_generated is None:
        run.smartva_records_generated = 0
    db.session.commit()

    log_progress(
        f"[{form_id}] attachments: queued {len(batches)} download batch(es) "
        f"for {len(items)} submission(s)…"
    )
    first_batch = batches[0]
    remaining_batches = batches[1:]
    run_attachment_sync_batch.delay(
        form_id=form_id,
        batch_map=first_batch,
        remaining_batches=remaining_batches,
        run_id=str(run_id),
        batch_index=1,
        batch_total=len(batches),
    )
    return len(batches)


def _schedule_enrichment_sync_for_form(run_id, form_id: str, upserted_map: dict[str, str], log_progress) -> int:
    """Schedule bounded enrichment batches for one form."""
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    items = list(upserted_map.items())
    batches = [
        dict(items[i:i + ENRICHMENT_SYNC_BATCH_SIZE])
        for i in range(0, len(items), ENRICHMENT_SYNC_BATCH_SIZE)
    ]
    if not batches:
        return 0

    log_progress(
        f"[{form_id}] enrich: queued {len(batches)} batch(es) for "
        f"{len(items)} changed submission(s)…"
    )
    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == run_id).with_for_update()
    ).scalar_one()
    run.attachment_forms_total = (run.attachment_forms_total or 0) + len(batches)
    if run.attachment_forms_completed is None:
        run.attachment_forms_completed = 0
    if run.attachment_downloaded is None:
        run.attachment_downloaded = 0
    if run.attachment_skipped is None:
        run.attachment_skipped = 0
    if run.attachment_errors is None:
        run.attachment_errors = 0
    if run.smartva_records_generated is None:
        run.smartva_records_generated = 0
    db.session.commit()
    first_batch = batches[0]
    remaining_batches = batches[1:]
    run_enrichment_sync_batch.delay(
        form_id=form_id,
        batch_map=first_batch,
        remaining_batches=remaining_batches,
        run_id=str(run_id),
        batch_index=1,
        batch_total=len(batches),
    )
    return len(batches)


def _schedule_repair_sync_for_form(run_id, form_id: str, repair_plan: dict[str, dict], log_progress) -> int:
    """Schedule stage-aware repair batches for one form."""
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    items = list(repair_plan.items())
    batches = [
        dict(items[i:i + ENRICHMENT_SYNC_BATCH_SIZE])
        for i in range(0, len(items), ENRICHMENT_SYNC_BATCH_SIZE)
    ]
    if not batches:
        return 0

    log_progress(
        f"[{form_id}] pipeline: queued {len(batches)} repair batch(es) for "
        f"{len(items)} submission(s)…"
    )
    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == run_id).with_for_update()
    ).scalar_one()
    run.attachment_forms_total = (run.attachment_forms_total or 0) + len(batches)
    if run.attachment_forms_completed is None:
        run.attachment_forms_completed = 0
    if run.attachment_downloaded is None:
        run.attachment_downloaded = 0
    if run.attachment_skipped is None:
        run.attachment_skipped = 0
    if run.attachment_errors is None:
        run.attachment_errors = 0
    if run.smartva_records_generated is None:
        run.smartva_records_generated = 0
    db.session.commit()

    first_batch = batches[0]
    remaining_batches = batches[1:]
    _dispatch_repair_batch(
        form_id=form_id,
        batch_map=first_batch,
        remaining_batches=remaining_batches,
        run_id=str(run_id),
        batch_index=1,
        batch_total=len(batches),
    )
    return len(batches)


def _build_repair_map_for_form(form_id: str, raw_submissions: list[dict], upserted_map: dict[str, str]) -> tuple[dict[str, dict], dict[str, int]]:
    """Return submissions that still need post-upsert repair for a form.

    Includes newly added/updated rows plus existing rows whose current payload is
    metadata-incomplete or whose local attachment cache is incomplete.
    """
    from app import db
    from app.models import VaSubmissions, VaSmartvaResults
    from app.models.va_selectives import VaStatuses
    from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion

    raw_by_sid = {
        submission.get("sid"): submission
        for submission in (raw_submissions or [])
        if submission.get("sid") and submission.get("KEY")
    }

    smartva_current_sq = (
        sa.select(VaSmartvaResults.va_sid.label("va_sid"))
        .join(
            VaSubmissions,
            sa.and_(
                VaSubmissions.va_sid == VaSmartvaResults.va_sid,
                VaSubmissions.active_payload_version_id
                == VaSmartvaResults.payload_version_id,
            ),
        )
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .group_by(VaSmartvaResults.va_sid)
        .subquery()
    )

    target_sids = list(raw_by_sid.keys()) if raw_by_sid else None
    present_attachment_files = _present_attachment_files_by_submission(
        form_id,
        target_sids=target_sids,
    )

    rows = db.session.execute(
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissionPayloadVersion.payload_data,
            VaSubmissions.va_summary,
            VaSubmissions.va_category_list,
            smartva_current_sq.c.va_sid.label("smartva_present_sid"),
        )
        .outerjoin(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .outerjoin(
            smartva_current_sq,
            smartva_current_sq.c.va_sid == VaSubmissions.va_sid,
        )
        .where(
            VaSubmissions.va_form_id == form_id,
            VaSubmissions.va_sid.in_(list(raw_by_sid.keys())) if raw_by_sid else sa.true(),
        )
    ).all()

    repair_map = {
        va_sid: {
            "instance_id": instance_id,
            "needs_metadata": True,
            "needs_attachments": True,
            "needs_smartva": True,
        }
        for va_sid, instance_id in (upserted_map or {}).items()
    }
    summary = {
        "metadata_missing": 0,
        "attachments_missing": 0,
        "smartva_missing": 0,
    }
    for va_sid, payload_data, va_summary, va_category_list, smartva_present_sid in rows:
        payload = payload_data or {}
        instance_id = (
            raw_by_sid.get(va_sid, {}).get("KEY")
            or payload.get("KEY")
            or (va_sid.rsplit(f"-{form_id.lower()}", 1)[0] if va_sid.endswith(f"-{form_id.lower()}") else None)
        )
        if not instance_id:
            continue
        metadata_complete = all(
            [
                va_summary is not None,
                va_category_list is not None,
                payload.get("FormVersion") is not None,
                payload.get("DeviceID") is not None,
                payload.get("SubmitterID") is not None,
                payload.get("instanceID") is not None,
                payload.get("AttachmentsExpected") is not None,
                payload.get("AttachmentsPresent") is not None,
            ]
        )
        try:
            attachments_expected = int(payload.get("AttachmentsExpected") or 0)
        except (TypeError, ValueError):
            attachments_expected = 0
        present_attachment_count = len(present_attachment_files.get(va_sid, set()))
        attachments_complete = present_attachment_count >= attachments_expected
        smartva_complete = smartva_present_sid is not None
        if not metadata_complete:
            summary["metadata_missing"] += 1
        if not attachments_complete:
            summary["attachments_missing"] += 1
        if not smartva_complete:
            summary["smartva_missing"] += 1
        if not metadata_complete or not attachments_complete or not smartva_complete:
            existing = repair_map.get(va_sid, {"instance_id": instance_id, "needs_metadata": False, "needs_attachments": False, "needs_smartva": False})
            existing["instance_id"] = existing.get("instance_id") or instance_id
            existing["needs_metadata"] = bool(existing.get("needs_metadata")) or (not metadata_complete)
            existing["needs_attachments"] = bool(existing.get("needs_attachments")) or (not attachments_complete)
            existing["needs_smartva"] = bool(existing.get("needs_smartva")) or (not smartva_complete)
            repair_map[va_sid] = existing

    return repair_map, summary


@shared_task(
    name="app.tasks.sync_tasks.run_odk_sync",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_odk_sync(self, triggered_by="scheduled", user_id=None):
    """Run ODK sync and record the outcome in va_sync_runs."""
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services.va_data_sync.va_data_sync_01_odkcentral import va_data_sync_odkcentral

    # Expire any orphaned "running" rows left by a crashed worker.
    cleanup_stale_runs()

    # Write "running" record in its own transaction so the dashboard sees it immediately.
    run = VaSyncRun(
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.sync_run_id
    log.info("OdkSync [%s]: started (triggered_by=%s)", run_id, triggered_by)

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        def dispatch_enrichment(va_form, upserted_map, progress_callback):
            _schedule_enrichment_sync_for_form(
                run_id,
                va_form.form_id,
                upserted_map,
                progress_callback,
            )

        result = va_data_sync_odkcentral(
            log_progress=log_progress,
            enrichment_sync_dispatcher=dispatch_enrichment,
        )
        run = db.session.get(VaSyncRun, run_id)
        failed_forms = result.get("failed_forms", []) if result else []
        if result:
            run.records_added = result.get("added", 0)
            run.records_updated = result.get("updated", 0)
            run.smartva_records_generated = result.get("smartva_updated", 0)
        if failed_forms:
            _append_run_error(run, f"Failed forms: {', '.join(failed_forms)}")
        if result and (
            result.get("enrichment_sync_forms_enqueued", 0)
            or result.get("attachment_sync_forms_enqueued", 0)
        ):
            run.status = "running"
        else:
            run.status = "partial" if failed_forms else "success"
            run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        log.info("OdkSync [%s]: finished status=%s", run_id, run.status)

    except SoftTimeLimitExceeded:
        log.error("OdkSync [%s]: soft time limit exceeded — task killed after 30 min", run_id)
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = "Task exceeded soft time limit (30 min) and was stopped."
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise

    except Exception as exc:
        log.error("OdkSync [%s]: failed — %s", run_id, exc, exc_info=True)
        _log_progress_exc(db, run_id, f"OdkSync run={run_id}", exc)
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_smartva_pending",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_smartva_pending(self, triggered_by="manual", user_id=None):
    """Run SmartVA only (no ODK download) and record in va_sync_runs."""
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services.va_data_sync.va_data_sync_01_odkcentral import va_smartva_run_pending

    cleanup_stale_runs()

    run = VaSyncRun(
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.sync_run_id
    log.info("SmartVAPending [%s]: started (triggered_by=%s)", run_id, triggered_by)

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        result = va_smartva_run_pending(log_progress=log_progress)
        run = db.session.get(VaSyncRun, run_id)
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        if result:
            run.records_added = result.get("smartva_updated", 0)
        db.session.commit()
        log.info("SmartVAPending [%s]: finished status=success", run_id)

    except SoftTimeLimitExceeded:
        log.error("SmartVAPending [%s]: soft time limit exceeded — task killed after 30 min", run_id)
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = "Task exceeded soft time limit (30 min) and was stopped."
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise

    except Exception as exc:
        log.error("SmartVAPending [%s]: failed — %s", run_id, exc, exc_info=True)
        _log_progress_exc(db, run_id, f"SmartVAPending run={run_id}", exc)
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_single_form_sync",
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def run_single_form_sync(self, form_id: str, triggered_by: str = "manual", user_id=None):
    """Download and upsert a single form, bypassing the delta check.

    Creates a va_sync_runs record with triggered_by="manual" so the dashboard
    can show the force-resync as a separate run entry.
    """
    import os
    from flask import current_app
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.models.va_forms import VaForms
    from app.models.map_project_site_odk import MapProjectSiteOdk
    import sqlalchemy as sa
    from app.utils import (
        va_odk_fetch_instance_ids,
        va_odk_fetch_submissions,
    )
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _mark_form_sync_issues,
        _upsert_form_submissions,
        SYNC_ISSUE_MISSING_IN_ODK,
    )

    run = VaSyncRun(
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.sync_run_id

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            raise ValueError(f"Form '{form_id}' not found in va_forms")
        _authorize_data_manager_form_sync(user_id, va_form)

        log_progress(f"[{form_id}] force-resync started — bypassing delta check")
        log.info("SingleFormSync [%s]: force-resync started.", form_id)

        snapshot_time = datetime.now(timezone.utc)
        odk_client = _get_single_form_odk_client(va_form)
        form_dir = os.path.join(current_app.config["APP_DATA"], form_id)
        media_dir = os.path.join(form_dir, "media")
        os.makedirs(media_dir, exist_ok=True)

        odk_ids = va_odk_fetch_instance_ids(va_form, client=odk_client)
        _mark_form_sync_issues(va_form, odk_ids)

        # Fetch ALL submissions (force-resync = no since filter)
        log_progress(f"[{form_id}] fetch: downloading submissions from ODK…")
        va_submissions_raw = va_odk_fetch_submissions(
            va_form,
            since=None,
            client=odk_client,
        )
        log_progress(
            f"[{form_id}] fetch: downloaded {len(va_submissions_raw)} submission(s) from ODK"
        )
        upserted_map: dict[str, str] = {}
        log_progress(
            f"[{form_id}] upsert: saving basic submission data for {len(va_submissions_raw)} submission(s)…"
        )
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form,
            va_submissions_raw,
            set(),
            upserted_map,
            enrich_payloads=False,
            defer_protected_updates=True,
        )
        db.session.commit()
        log_progress(
            f"[{form_id}] upsert: complete — +{added} added, {updated} updated"
            + (f", {skipped} skipped" if skipped else "")
        )
        repair_map, repair_summary = _build_repair_map_for_form(
            form_id,
            va_submissions_raw,
            upserted_map,
        )
        if repair_map:
            log_progress(
                f"[{form_id}] Backfill: queueing {len(repair_map)} submission(s) for repair "
                f"(metadata gaps: {repair_summary['metadata_missing']}, "
                f"missing local attachment files: {repair_summary['attachments_missing']}, "
                f"SmartVA gaps: {repair_summary['smartva_missing']})…"
            )
            _schedule_enrichment_sync_for_form(
                run_id,
                form_id,
                repair_map,
                log_progress=log_progress,
            )

        # Update last_synced_at
        mapping = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == va_form.project_id,
                MapProjectSiteOdk.site_id == va_form.site_id,
            )
        )
        if mapping:
            mapping.last_synced_at = snapshot_time
            db.session.commit()

        run = db.session.get(VaSyncRun, run_id)
        run.records_added = added
        run.records_updated = updated
        run.smartva_records_generated = 0
        if repair_map:
            db.session.commit()
            run = db.session.get(VaSyncRun, run_id)
            run.status = "running"
        else:
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        log.info(
            "SingleFormSync [%s]: queued repair sync — added=%d updated=%d repaired=%d",
            form_id,
            added,
            updated,
            len(repair_map),
        )

    except SoftTimeLimitExceeded:
        log.error("SingleFormSync [%s]: soft time limit exceeded — task killed after 10 min", form_id)
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = "Task exceeded soft time limit (10 min) and was stopped."
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise

    except Exception as exc:
        log.error("SingleFormSync [%s]: failed — %s", form_id, exc, exc_info=True)
        _log_progress_exc(db, run_id, f"SingleFormSync form={form_id}", exc)
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_single_form_backfill",
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def run_single_form_backfill(self, form_id: str, triggered_by: str = "backfill", user_id=None):
    """Repair local gaps for one form without doing a full force-resync."""
    import os
    from flask import current_app
    from app import db
    from app.models.va_forms import VaForms
    from app.models.va_submissions import VaSubmissions
    from app.models.va_sync_runs import VaSyncRun
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _mark_form_sync_issues,
        _upsert_form_submissions,
    )
    from app.utils import (
        va_odk_fetch_instance_ids,
        va_odk_fetch_submissions_by_ids,
    )

    run = VaSyncRun(
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.sync_run_id

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            raise ValueError(f"Form '{form_id}' not found in va_forms")
        _authorize_data_manager_form_sync(user_id, va_form)

        log_progress(f"[{form_id}] backfill started — checking ODK and local gaps")

        odk_client = _get_single_form_odk_client(va_form)
        form_dir = os.path.join(current_app.config["APP_DATA"], form_id)
        media_dir = os.path.join(form_dir, "media")
        os.makedirs(media_dir, exist_ok=True)

        odk_ids = va_odk_fetch_instance_ids(va_form, client=odk_client)
        _mark_form_sync_issues(va_form, odk_ids)

        form_id_lower = form_id.lower()
        local_sids = set(
            db.session.scalars(
                sa.select(VaSubmissions.va_sid).where(VaSubmissions.va_form_id == form_id)
            ).all()
        )
        missing_ids = [
            instance_id
            for instance_id in odk_ids
            if f"{instance_id}-{form_id_lower}" not in local_sids
        ]
        log_progress(
            f"[{form_id}] backfill: {len(missing_ids)} submission(s) missing thin local data"
        )

        added = 0
        updated = 0
        discarded = 0
        skipped = 0
        upserted_map: dict[str, str] = {}
        raw_records_for_repair: list[dict] = []

        gap_batch_size = 50
        for batch_start in range(0, len(missing_ids), gap_batch_size):
            batch_ids = missing_ids[batch_start: batch_start + gap_batch_size]
            batch_records = va_odk_fetch_submissions_by_ids(
                va_form,
                batch_ids,
                client=odk_client,
                log_progress=log_progress,
            )
            if not batch_records:
                continue
            raw_records_for_repair.extend(batch_records)
            batch_upserted_map: dict[str, str] = {}
            b_added, b_updated, b_discarded, b_skipped = _upsert_form_submissions(
                va_form,
                batch_records,
                set(),
                batch_upserted_map,
                enrich_payloads=False,
                defer_protected_updates=True,
            )
            db.session.commit()
            upserted_map.update(batch_upserted_map)
            added += b_added
            updated += b_updated
            discarded += b_discarded
            skipped += b_skipped
            done = min(batch_start + gap_batch_size, len(missing_ids))
            log_progress(
                f"[{form_id}] backfill data: fetched {done}/{len(missing_ids)} missing submission(s)"
            )

        repair_map, repair_summary = _build_repair_map_for_form(
            form_id,
            raw_records_for_repair,
            upserted_map,
        )
        log_progress(
            f"[{form_id}] Backfill: queueing {len(repair_map)} submission(s) for repair "
            f"(metadata gaps: {repair_summary['metadata_missing']}, "
            f"missing local attachment files: {repair_summary['attachments_missing']}, "
            f"SmartVA gaps: {repair_summary['smartva_missing']})"
        )

        run = db.session.get(VaSyncRun, run_id)
        run.records_added = added
        run.records_updated = updated
        run.smartva_records_generated = 0

        if repair_map:
            _schedule_repair_sync_for_form(
                run_id,
                form_id,
                repair_map,
                log_progress=log_progress,
            )
            run.status = "running"
        else:
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            log_progress(
                f"[{form_id}] Backfill: no local metadata, attachment file, or SmartVA gaps found"
            )
        db.session.commit()
        log.info(
            "SingleFormBackfill [%s]: added=%d updated=%d repaired=%d skipped=%d discarded=%d",
            form_id,
            added,
            updated,
            len(repair_map),
            skipped,
            discarded,
        )
    except Exception as exc:
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_legacy_attachment_repair",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_legacy_attachment_repair(
    self,
    triggered_by: str = "legacy-attachment-repair",
    user_id=None,
):
    """Populate storage_name for legacy media attachment rows."""
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from scripts.migrate_attachment_storage_names import (
        repair_attachment_storage_names,
    )

    run = VaSyncRun(
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.sync_run_id

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        log_progress("legacy-attachment repair: started")
        result = repair_attachment_storage_names(
            apply=True,
            batch_size=500,
            progress_callback=log_progress,
            verbose=False,
        )
        log_progress(
            "legacy-attachment repair: complete — "
            f"{result['migrated']} migrated, {result['missing']} missing"
        )
        run = db.session.get(VaSyncRun, run_id)
        run.records_updated = int(result.get("migrated") or 0)
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
    except SoftTimeLimitExceeded:
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = (
                    "Task exceeded soft time limit (30 min) and was stopped."
                )
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise
    except Exception as exc:
        _log_progress_exc(db, run_id, "LegacyAttachmentRepair", exc)
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_enrichment_sync_batch",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def run_enrichment_sync_batch(
    self,
    *,
    form_id: str,
    batch_map: dict[str, str],
    remaining_batches: list[dict[str, str]] | None = None,
    run_id: str,
    batch_index: int = 1,
    batch_total: int = 1,
):
    """Enrich one bounded batch of submissions for a form."""
    from app import db
    from app.models import VaForms, VaSubmissions
    from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _attach_all_odk_comments,
        _finalize_enriched_submissions_for_form,
    )

    db.session.rollback()
    va_form = db.session.get(VaForms, form_id)
    if va_form is None:
        return {
            "enriched": 0,
            "errors": len(batch_map or {}),
            "error_message": f"Form '{form_id}' not found for enrichment batch.",
        }

    batch_plan = _normalize_batch_plan(batch_map)
    metadata_sids = [
        va_sid for va_sid, item in batch_plan.items()
        if item.get("needs_metadata")
    ]
    submission_rows = db.session.execute(
        sa.select(VaSubmissions.va_sid, VaSubmissionPayloadVersion.payload_data)
        .outerjoin(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .where(VaSubmissions.va_sid.in_(metadata_sids))
    ).all() if metadata_sids else []
    if not submission_rows:
        if _batch_stage_counts(batch_plan)["attachments"] > 0:
            run_attachment_sync_batch.delay(
                form_id=form_id,
                batch_map=batch_plan,
                remaining_batches=remaining_batches or [],
                run_id=run_id,
                batch_index=batch_index,
                batch_total=batch_total,
            )
        elif _batch_stage_counts(batch_plan)["smartva"] > 0:
            run_smartva_sync_batch.delay(
                form_id=form_id,
                batch_map=batch_plan,
                remaining_batches=remaining_batches or [],
                run_id=run_id,
                batch_index=batch_index,
                batch_total=batch_total,
            )
        else:
            _finalize_repair_batch(
                form_id=form_id,
                run_id=run_id,
                batch_plan=batch_plan,
                remaining_batches=remaining_batches or [],
                batch_index=batch_index,
                batch_total=batch_total,
                downloaded=0,
                skipped=0,
                errors=0,
                smartva_updated=0,
                error_messages=[],
            )
        return {"enriched": 0, "errors": 0, "error_message": None}

    raw_submissions = [dict(payload_data or {}) for _, payload_data in submission_rows]
    upserted_map = {
        va_sid: (payload_data or {}).get("KEY", "")
        for va_sid, payload_data in submission_rows
    }
    amended_sids: set[str] = set()
    _release_read_transaction(va_form)
    odk_client = _get_single_form_odk_client(va_form)

    try:
        _log_progress(
            db,
            run_id,
            (
                f"[{form_id}] enrich: batch {batch_index}/{batch_total} "
                f"starting for {len(submission_rows)} submission(s)…"
            ),
        )
        raw_submissions = _attach_all_odk_comments(
            va_form,
            raw_submissions,
            client=odk_client,
            log_progress=lambda msg: _log_progress(db, run_id, msg),
        )
        enriched_count = _finalize_enriched_submissions_for_form(
            va_form,
            raw_submissions,
            upserted_map,
            amended_sids,
            client=odk_client,
            log_progress=lambda msg: _log_progress(db, run_id, msg),
        )
        db.session.commit()
        _log_progress(
            db,
            run_id,
            (
                f"[{form_id}] enrich: batch {batch_index}/{batch_total} "
                f"complete — {enriched_count}/{len(submission_rows)} submission(s) enriched"
            ),
        )
        for item in batch_plan.values():
            item["needs_metadata"] = False
        if _batch_stage_counts(batch_plan)["attachments"] > 0:
            run_attachment_sync_batch.delay(
                form_id=form_id,
                batch_map=batch_plan,
                remaining_batches=remaining_batches or [],
                run_id=run_id,
                batch_index=batch_index,
                batch_total=batch_total,
            )
        elif _batch_stage_counts(batch_plan)["smartva"] > 0:
            run_smartva_sync_batch.delay(
                form_id=form_id,
                batch_map=batch_plan,
                remaining_batches=remaining_batches or [],
                run_id=run_id,
                batch_index=batch_index,
                batch_total=batch_total,
            )
        else:
            _finalize_repair_batch(
                form_id=form_id,
                run_id=run_id,
                batch_plan=batch_plan,
                remaining_batches=remaining_batches or [],
                batch_index=batch_index,
                batch_total=batch_total,
                downloaded=0,
                skipped=0,
                errors=0,
                smartva_updated=0,
                error_messages=[],
            )
        return {
            "enriched": enriched_count,
            "errors": 0,
            "error_message": None,
        }
    except SoftTimeLimitExceeded:
        log.error(
            "EnrichmentSync [%s] batch %d/%d: soft time limit exceeded — task killed",
            form_id, batch_index, batch_total,
        )
        raise

    except Exception as exc:
        log.error(
            "EnrichmentSync [%s] batch %d/%d: failed — %s",
            form_id, batch_index, batch_total, exc, exc_info=True,
        )
        db.session.rollback()
        _log_progress(
            db,
            run_id,
            f"[{form_id}] enrich: batch {batch_index}/{batch_total} FAILED — {exc}",
        )
        _log_progress_exc(db, run_id, f"EnrichmentSync form={form_id} batch={batch_index}/{batch_total}", exc)
        from uuid import UUID
        from app.models.va_sync_runs import VaSyncRun

        run = db.session.execute(
            sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(run_id)).with_for_update()
        ).scalar_one_or_none()
        if run is not None:
            run.attachment_forms_completed = (run.attachment_forms_completed or 0) + 1
            run.attachment_errors = (run.attachment_errors or 0) + len(submission_rows)
            _append_run_error(
                run,
                f"[{form_id}] enrich batch {batch_index}/{batch_total} failed: {exc}",
            )
            db.session.commit()
        if remaining_batches:
            next_batch = remaining_batches[0]
            next_remaining_batches = remaining_batches[1:]
            _log_progress(
                db,
                run_id,
                f"[{form_id}] enrich: continuing with batch {batch_index + 1}/{batch_total}…",
            )
            run_enrichment_sync_batch.delay(
                form_id=form_id,
                batch_map=next_batch,
                remaining_batches=next_remaining_batches,
                run_id=run_id,
                batch_index=batch_index + 1,
                batch_total=batch_total,
            )
        return {
            "enriched": 0,
            "errors": len(submission_rows),
            "error_message": str(exc)[:500],
        }


@shared_task(
    name="app.tasks.sync_tasks.finalize_form_enrichment_sync",
    bind=True,
    soft_time_limit=900,
    time_limit=1800,
)
def finalize_form_enrichment_sync(self, results, *, form_id: str, va_sids: list[str], run_id: str):
    """Finalize per-submission enrichment batches for one form, then queue attachments."""
    from uuid import UUID
    from app import db
    from app.models import VaSubmissions
    from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
    from app.models.va_sync_runs import VaSyncRun

    db.session.rollback()
    enriched = sum(int((row or {}).get("enriched", 0)) for row in results or [])
    errors = sum(int((row or {}).get("errors", 0)) for row in results or [])
    error_messages = [
        (row or {}).get("error_message")
        for row in results or []
        if (row or {}).get("error_message")
    ]

    _log_progress(
        db,
        run_id,
        f"[{form_id}] enrich: complete — {enriched} submission(s) enriched",
    )

    upserted_map = {}
    if va_sids:
        rows = db.session.execute(
            sa.select(VaSubmissions.va_sid, VaSubmissionPayloadVersion.payload_data)
            .outerjoin(
                VaSubmissionPayloadVersion,
                VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
            )
            .where(VaSubmissions.va_sid.in_(va_sids))
        ).all()
        upserted_map = {
            va_sid: (payload_data or {}).get("KEY", "")
            for va_sid, payload_data in rows
            if (payload_data or {}).get("KEY")
        }

    if not upserted_map:
        error_messages.append(
            f"[{form_id}] enrich finalize: no submissions available for attachment sync."
        )

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(run_id)).with_for_update()
    ).scalar_one_or_none()
    if run is None:
        return

    for message in error_messages:
        _append_run_error(run, message)

    if upserted_map:
        _schedule_attachment_sync_for_form(run_id, form_id, upserted_map, lambda msg: _log_progress(db, run_id, msg))
    else:
        run.status = "partial" if (run.error_message or errors) else run.status
        run.finished_at = datetime.now(timezone.utc)
        _log_progress(
            db,
            run_id,
            f"[{form_id}] pipeline: complete — {enriched} submission(s) enriched, 0 attachments queued",
        )
        db.session.commit()
        return

    db.session.commit()


@shared_task(
    name="app.tasks.sync_tasks.run_attachment_sync_batch",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def run_attachment_sync_batch(
    self,
    *,
    form_id: str,
    batch_map: dict[str, dict] | dict[str, str],
    remaining_batches: list[dict] | None = None,
    run_id: str,
    batch_index: int = 1,
    batch_total: int = 1,
):
    """Sync one bounded attachment batch for a form."""
    import os
    from flask import current_app
    from app import db
    from app.models.va_forms import VaForms
    from app.utils import va_odk_sync_form_attachments
    from app.services.workflow.definition import WORKFLOW_ATTACHMENT_SYNC_PENDING
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import (
        WorkflowTransitionError,
        mark_attachment_sync_completed,
        system_actor,
    )

    db.session.rollback()
    batch_plan = _normalize_batch_plan(batch_map)
    attachment_map = {
        va_sid: item.get("instance_id") or ""
        for va_sid, item in batch_plan.items()
        if item.get("needs_attachments")
    }
    va_form = db.session.get(VaForms, form_id)
    if va_form is None:
        return {
            "downloaded": 0,
            "skipped": 0,
            "errors": len(attachment_map),
            "error_message": f"Form '{form_id}' not found for attachment batch.",
        }

    form_dir = os.path.join(current_app.config["APP_DATA"], form_id)
    media_dir = os.path.join(form_dir, "media")
    os.makedirs(media_dir, exist_ok=True)
    _release_read_transaction(va_form)
    try:
        _log_progress(
            db,
            run_id,
            (
                f"[{form_id}] attachments: batch {batch_index}/{batch_total} "
                f"starting for {len(attachment_map)} submission(s)…"
            ),
        )
        totals = {"downloaded": 0, "skipped": 0, "errors": 0}
        if attachment_map:
            totals = va_odk_sync_form_attachments(
                va_form,
                attachment_map,
                media_dir,
                client_factory=lambda: _get_single_form_odk_client(va_form),
            )
        transitioned_count = 0
        transition_errors: list[str] = []
        for va_sid in batch_plan.keys():
            if get_submission_workflow_state(va_sid) != WORKFLOW_ATTACHMENT_SYNC_PENDING:
                continue
            try:
                mark_attachment_sync_completed(
                    va_sid,
                    reason="attachments_synced_for_current_payload",
                    actor=system_actor(),
                )
                transitioned_count += 1
            except WorkflowTransitionError as exc:
                transition_errors.append(f"{va_sid}: {exc}")
        db.session.commit()
        for item in batch_plan.values():
            if item.get("needs_attachments"):
                item["needs_attachments"] = False
        if _batch_stage_counts(batch_plan)["smartva"] > 0:
            _log_progress(
                db,
                run_id,
                f"[{form_id}] workflow: attachments synced for batch {batch_index}/{batch_total}"
                + (
                    f"; {transitioned_count} submission(s) advanced to SmartVA"
                    if transitioned_count
                    else "; running SmartVA on the repaired batch"
                ),
            )
            run_smartva_sync_batch.delay(
                form_id=form_id,
                batch_map=batch_plan,
                remaining_batches=remaining_batches or [],
                run_id=run_id,
                batch_index=batch_index,
                batch_total=batch_total,
            )
        else:
            _finalize_repair_batch(
                form_id=form_id,
                run_id=run_id,
                batch_plan=batch_plan,
                remaining_batches=remaining_batches or [],
                batch_index=batch_index,
                batch_total=batch_total,
                downloaded=totals["downloaded"],
                skipped=totals["skipped"],
                errors=totals["errors"] + len(transition_errors),
                smartva_updated=0,
                error_messages=transition_errors,
            )
        return {
            "downloaded": totals["downloaded"],
            "skipped": totals["skipped"],
            "errors": totals["errors"],
            "error_message": None,
        }
    except SoftTimeLimitExceeded:
        log.error(
            "AttachmentSync [%s] batch %d/%d: soft time limit exceeded — task killed",
            form_id, batch_index, batch_total,
        )
        raise

    except Exception as exc:
        log.error(
            "AttachmentSync [%s] batch %d/%d: failed — %s",
            form_id, batch_index, batch_total, exc, exc_info=True,
        )
        db.session.rollback()
        _log_progress(
            db,
            run_id,
            f"[{form_id}] attachments: batch {batch_index}/{batch_total} FAILED — {exc}",
        )
        _log_progress_exc(db, run_id, f"AttachmentSync form={form_id} batch={batch_index}/{batch_total}", exc)
        from uuid import UUID
        from app.models.va_sync_runs import VaSyncRun

        run = db.session.execute(
            sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(run_id)).with_for_update()
        ).scalar_one_or_none()
        if run is not None:
            run.attachment_forms_completed = (run.attachment_forms_completed or 0) + 1
            run.attachment_errors = (run.attachment_errors or 0) + len(attachment_map)
            _append_run_error(
                run,
                f"[{form_id}] attachment batch {batch_index}/{batch_total} failed: {exc}",
            )
            db.session.commit()
        if remaining_batches:
            next_batch = remaining_batches[0]
            next_remaining_batches = remaining_batches[1:]
            _log_progress(
                db,
                run_id,
                f"[{form_id}] attachments: queueing next batch {batch_index + 1}/{batch_total}…",
            )
            _dispatch_repair_batch(
                form_id=form_id,
                batch_map=next_batch,
                remaining_batches=next_remaining_batches,
                run_id=run_id,
                batch_index=batch_index + 1,
                batch_total=batch_total,
            )
        return {
            "downloaded": 0,
            "skipped": 0,
            "errors": len(attachment_map),
            "error_message": str(exc)[:500],
        }


@shared_task(
    name="app.tasks.sync_tasks.run_smartva_sync_batch",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def run_smartva_sync_batch(
    self,
    *,
    form_id: str,
    batch_map: dict[str, dict] | dict[str, str],
    remaining_batches: list[dict] | None = None,
    run_id: str,
    batch_index: int = 1,
    batch_total: int = 1,
):
    """Run SmartVA for one bounded batch of submissions."""
    from app import db
    from app.models.va_forms import VaForms
    from app.services import smartva_service

    db.session.rollback()
    batch_plan = _normalize_batch_plan(batch_map)
    target_sids = [
        va_sid for va_sid, item in batch_plan.items()
        if item.get("needs_smartva")
    ]
    va_form = db.session.get(VaForms, form_id)
    if va_form is None:
        return {
            "smartva_updated": 0,
            "errors": len(target_sids),
            "error_message": f"Form '{form_id}' not found for SmartVA batch.",
        }

    _release_read_transaction(va_form)
    try:
        _log_progress(
            db,
            run_id,
            f"SmartVA {form_id}: starting for batch {batch_index}/{batch_total} ({len(target_sids)} submission(s)).",
        )
        smartva_updated = 0
        if target_sids:
            smartva_updated = smartva_service.generate_for_form(
                va_form,
                target_sids=set(target_sids),
                log_progress=lambda msg: _log_progress(db, run_id, msg),
            )
        _log_progress(
            db,
            run_id,
            f"SmartVA {form_id}: finished — {smartva_updated} result(s) generated.",
        )
        for item in batch_plan.values():
            if item.get("needs_smartva"):
                item["needs_smartva"] = False
        _finalize_repair_batch(
            form_id=form_id,
            run_id=run_id,
            batch_plan=batch_plan,
            remaining_batches=remaining_batches or [],
            batch_index=batch_index,
            batch_total=batch_total,
            downloaded=0,
            skipped=0,
            errors=0,
            smartva_updated=smartva_updated,
            error_messages=[],
        )
        return {
            "smartva_updated": smartva_updated,
            "errors": 0,
            "error_message": None,
        }
    except SoftTimeLimitExceeded:
        log.error(
            "SmartVASync [%s] batch %d/%d: soft time limit exceeded — task killed",
            form_id, batch_index, batch_total,
        )
        raise

    except Exception as exc:
        log.error(
            "SmartVASync [%s] batch %d/%d: failed — %s",
            form_id, batch_index, batch_total, exc, exc_info=True,
        )
        db.session.rollback()
        _log_progress(db, run_id, f"SmartVA {form_id}: FAILED — {exc}")
        _log_progress_exc(db, run_id, f"SmartVASync form={form_id} batch={batch_index}/{batch_total}", exc)
        _finalize_repair_batch(
            form_id=form_id,
            run_id=run_id,
            batch_plan=batch_plan,
            remaining_batches=remaining_batches or [],
            batch_index=batch_index,
            batch_total=batch_total,
            downloaded=0,
            skipped=0,
            errors=len(target_sids),
            smartva_updated=0,
            error_messages=[f"SmartVA {form_id}: {exc}"],
        )
        return {
            "smartva_updated": 0,
            "errors": len(target_sids),
            "error_message": str(exc)[:500],
        }


def _finalize_repair_batch(
    *,
    form_id: str,
    run_id: str,
    batch_plan: dict[str, dict],
    remaining_batches: list[dict] | None = None,
    batch_index: int = 1,
    batch_total: int = 1,
    downloaded: int = 0,
    skipped: int = 0,
    errors: int = 0,
    smartva_updated: int = 0,
    error_messages: list[str] | None = None,
):
    """Finalize one repair batch, update counters, and queue the next batch."""
    from uuid import UUID
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    db.session.rollback()
    error_messages = error_messages or []
    va_sids = list(batch_plan.keys())

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(run_id)).with_for_update()
    ).scalar_one_or_none()
    if run is None:
        return

    post_commit_messages: list[str] = []
    run.attachment_forms_completed = (run.attachment_forms_completed or 0) + 1
    run.attachment_downloaded = (run.attachment_downloaded or 0) + downloaded
    run.attachment_skipped = (run.attachment_skipped or 0) + skipped
    run.attachment_errors = (run.attachment_errors or 0) + errors
    run.smartva_records_generated = (run.smartva_records_generated or 0) + smartva_updated
    for message in error_messages:
        _append_run_error(run, message)
    post_commit_messages.append(
        (
            f"[{form_id}] pipeline: batch {batch_index}/{batch_total} complete — "
            f"{len(va_sids)} submission(s), "
            f"{downloaded} attachment file(s) downloaded, "
            f"{smartva_updated} SmartVA result(s) generated"
            + (f", {errors} attachment error(s)" if errors else "")
        )
    )

    if (run.attachment_forms_completed or 0) >= (run.attachment_forms_total or 0):
        run.finished_at = datetime.now(timezone.utc)
        run.status = "partial" if run.error_message or (run.attachment_errors or 0) else "success"
        post_commit_messages.append(
            (
                "Sync finished: "
                f"{run.records_added or 0} added, "
                f"{run.records_updated or 0} updated, "
                f"{run.attachment_downloaded or 0} attachments downloaded, "
                f"{run.smartva_records_generated or 0} SmartVA result(s) generated."
            )
        )

    db.session.commit()

    for message in post_commit_messages:
        _log_progress(db, run_id, message)

    if remaining_batches:
        next_batch = remaining_batches[0]
        next_remaining_batches = remaining_batches[1:]
        _log_progress(
            db,
            run_id,
            f"[{form_id}] pipeline: batch {batch_index}/{batch_total} complete; "
            f"queueing next batch {batch_index + 1}/{batch_total} "
            f"for {len(next_batch)} submission(s)…",
        )
        _dispatch_repair_batch(
            form_id=form_id,
            batch_map=next_batch,
            remaining_batches=next_remaining_batches,
            run_id=run_id,
            batch_index=batch_index + 1,
            batch_total=batch_total,
        )


@shared_task(
    name="app.tasks.sync_tasks.finalize_form_attachment_sync",
    bind=True,
    soft_time_limit=900,
    time_limit=1800,
)
def finalize_form_attachment_sync(
    self,
    results,
    *,
    form_id: str,
    va_sids: list[str],
    run_id: str,
    remaining_batches: list[dict[str, str]] | None = None,
    batch_index: int = 1,
    batch_total: int = 1,
):
    """Compatibility wrapper for older queued callbacks."""
    downloaded = sum(int((row or {}).get("downloaded", 0)) for row in results or [])
    skipped = sum(int((row or {}).get("skipped", 0)) for row in results or [])
    errors = sum(int((row or {}).get("errors", 0)) for row in results or [])
    error_messages = [
        (row or {}).get("error_message")
        for row in results or []
        if (row or {}).get("error_message")
    ]
    return _finalize_repair_batch(
        form_id=form_id,
        run_id=run_id,
        batch_plan={va_sid: {"instance_id": "", "needs_metadata": False, "needs_attachments": False, "needs_smartva": False} for va_sid in va_sids},
        remaining_batches=remaining_batches,
        batch_index=batch_index,
        batch_total=batch_total,
        downloaded=downloaded,
        skipped=skipped,
        errors=errors,
        smartva_updated=0,
        error_messages=error_messages,
    )


@shared_task(
    name="app.tasks.sync_tasks.run_single_submission_sync",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def run_single_submission_sync(self, va_sid: str, triggered_by: str = "manual", user_id=None):
    """Fetch and upsert one submission from ODK for its mapped form."""
    from datetime import datetime as _dt
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.models import VaForms, VaSubmissions
    from app.services.odk_review_service import resolve_odk_instance_id
    from app.utils import (
        va_odk_fetch_instance_ids,
        va_odk_fetch_submissions_by_ids,
    )
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _mark_form_sync_issues,
        _upsert_form_submissions,
        SYNC_ISSUE_MISSING_IN_ODK,
    )
    import os
    from flask import current_app
    from app.models import VaStatuses, VaSubmissionsAuditlog

    run = VaSyncRun(
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        started_at=_dt.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.sync_run_id

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        submission = db.session.get(VaSubmissions, va_sid)
        if submission is None:
            raise ValueError(f"Submission '{va_sid}' not found.")

        va_form = db.session.get(VaForms, submission.va_form_id)
        if va_form is None:
            raise ValueError(f"Form '{submission.va_form_id}' not found.")
        _authorize_data_manager_submission_sync(user_id, submission, va_form)

        odk_client = _get_single_form_odk_client(va_form)
        instance_id = resolve_odk_instance_id(va_sid)
        log_progress(f"[{va_form.form_id}] fetch: downloading submissions from ODK…")
        records = va_odk_fetch_submissions_by_ids(
            va_form,
            [instance_id],
            client=odk_client,
        )
        log_progress(
            f"[{va_form.form_id}] fetch: downloaded {len(records)} submission(s) from ODK"
        )

        if not records:
            submission.va_sync_issue_code = SYNC_ISSUE_MISSING_IN_ODK
            submission.va_sync_issue_detail = (
                "Submission could not be fetched from active ODK submissions."
            )
            submission.va_sync_issue_updated_at = _dt.now(timezone.utc)
            db.session.commit()

            run = db.session.get(VaSyncRun, run_id)
            run.status = "partial"
            run.finished_at = _dt.now(timezone.utc)
            run.error_message = "Submission is missing from ODK."
            db.session.commit()
            return

        upserted_map = {}
        log_progress(
            f"[{va_form.form_id}] upsert: saving basic submission data for {len(records)} submission(s)…"
        )
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form,
            records,
            amended_sids=set(),
            upserted_map=upserted_map,
            client=odk_client,
            enrich_payloads=False,
            defer_protected_updates=True,
        )
        db.session.commit()
        log_progress(
            f"[{va_form.form_id}] upsert: complete — +{added} added, {updated} updated"
            + (f", {skipped} skipped" if skipped else "")
        )
        if upserted_map:
            log_progress(
                f"[{va_form.form_id}] enrich: queueing {len(upserted_map)} changed "
                f"submission(s) for batched metadata enrichment…"
            )
            _schedule_enrichment_sync_for_form(
                run_id,
                va_form.form_id,
                upserted_map,
                log_progress=log_progress,
            )
        _mark_form_sync_issues(va_form, va_odk_fetch_instance_ids(va_form, client=odk_client))
        db.session.commit()

        form_dir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
        media_dir = os.path.join(form_dir, "media")
        os.makedirs(media_dir, exist_ok=True)
        run = db.session.get(VaSyncRun, run_id)
        run.records_added = added
        run.records_updated = updated
        run.smartva_records_generated = 0
        if upserted_map:
            db.session.commit()
            run = db.session.get(VaSyncRun, run_id)
            run.status = "running"
        else:
            run.status = "success"
            run.finished_at = _dt.now(timezone.utc)
        db.session.commit()
        log_progress(
            f"[{va_sid}] refreshed from ODK: +{added} added, {updated} updated"
            + (f", {discarded} discarded" if discarded else "")
            + (f", {skipped} skipped" if skipped else "")
        )
    except Exception as exc:
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = _dt.now(timezone.utc)
                run.error_message = str(exc)[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_smartva_for_submission",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def run_smartva_for_submission(self, va_sid: str, triggered_by: str = "manual"):
    """Run SmartVA generation for a single submission.

    Thin wrapper around smartva_service.generate_for_submission — used when
    a data manager accepts an upstream ODK change and we want to immediately
    re-queue SmartVA without a full ODK re-sync.
    """
    from app import db
    from app.services import smartva_service

    log.info("SmartVA task [%s]: starting (triggered_by=%s).", va_sid, triggered_by)
    try:
        saved = smartva_service.generate_for_submission(va_sid)
        log.info("SmartVA task [%s]: %d result(s) saved.", va_sid, saved)
        return {"va_sid": va_sid, "smartva_updated": saved}
    except Exception as exc:
        db.session.rollback()
        log.error("SmartVA task [%s]: failed — %s", va_sid, exc, exc_info=True)
        raise


def ensure_sync_scheduled():
    """Seed the default ODK sync periodic task (every 6 hours). Idempotent."""
    try:
        from app import db

        with db.engine.begin() as conn:
            # Ensure interval exists
            interval_id = conn.execute(sa.text(
                "SELECT id FROM public.celery_intervalschedule "
                "WHERE every = 6 AND period = 'hours' LIMIT 1"
            )).scalar()
            if interval_id is None:
                interval_id = conn.execute(sa.text(
                    "INSERT INTO public.celery_intervalschedule (every, period) "
                    "VALUES (6, 'hours') RETURNING id"
                )).scalar()

            # Ensure periodic task exists
            exists = conn.execute(sa.text(
                "SELECT id FROM public.celery_periodictask WHERE name = :name LIMIT 1"
            ), {"name": "ODK Sync — every 6 hours"}).scalar()

            if not exists:
                conn.execute(sa.text("""
                    INSERT INTO public.celery_periodictask
                        (name, task, args, kwargs, queue, exchange, routing_key, headers,
                         priority, one_off, enabled, total_run_count, description,
                         discriminator, schedule_id)
                    VALUES
                        (:name, :task, '[]', :kwargs, NULL, NULL, NULL, '{}',
                         NULL, false, true, 0, '',
                         'intervalschedule', :schedule_id)
                """), {
                    "name": "ODK Sync — every 6 hours",
                    "task": "app.tasks.sync_tasks.run_odk_sync",
                    "kwargs": json.dumps({"triggered_by": "scheduled"}),
                    "schedule_id": interval_id,
                })
                # Signal beat to reload its schedule
                conn.execute(sa.text(
                    "INSERT INTO public.celery_periodictaskchanged (last_update) "
                    "VALUES (NOW()) ON CONFLICT DO NOTHING"
                ))

        log.info("Sync beat schedule seeded: every 6 hours.")
    except Exception as e:
        log.warning("Could not seed sync schedule: %s", e)


def cleanup_stale_runs():
    """Mark orphaned 'running' rows as 'error'.

    Called on worker startup and before each new sync run.  The threshold
    is 45 minutes — well under the Celery soft_time_limit (30 min), so any
    run older than that is certainly dead.
    """
    try:
        from app import db
        result = db.session.execute(sa.text("""
            UPDATE va_sync_runs
            SET status = 'error',
                finished_at = NOW(),
                error_message = 'Stale run — worker likely restarted before completion'
            WHERE status = 'running'
              AND started_at < NOW() - INTERVAL '45 minutes'
        """))
        if result.rowcount:
            log.warning("Cleaned up %d stale 'running' sync run(s).", result.rowcount)
        db.session.commit()
    except Exception as e:
        log.warning("Could not clean up stale sync runs: %s", e)
        try:
            db.session.rollback()
        except Exception:
            pass


@shared_task(
    name="app.tasks.sync_tasks.refresh_submission_analytics_mv_task",
    bind=True,
    soft_time_limit=900,
    time_limit=1800,
)
def refresh_submission_analytics_mv_task(self):
    """Refresh the submission analytics materialized views and record the run."""
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services.submission_analytics_mv import refresh_submission_analytics_mv

    run = VaSyncRun(
        triggered_by=ANALYTICS_MV_TRIGGER,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = run.sync_run_id

    try:
        _log_progress(db, run_id, "Refreshing submission analytics materialized views.")
        refresh_submission_analytics_mv(concurrently=True)
        run = db.session.get(VaSyncRun, run_id)
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        run.records_updated = db.session.scalar(
            sa.text("SELECT COUNT(*) FROM public.va_submission_analytics_core_mv")
        )
        db.session.commit()
        _log_progress(
            db,
            run_id,
            f"Submission analytics materialized views refreshed: {run.records_updated} rows.",
        )
    except Exception as exc:
        try:
            run = db.session.get(VaSyncRun, run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:2000]
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@shared_task(
    name="app.tasks.sync_tasks.release_stale_coding_allocations_task",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def release_stale_coding_allocations_task(self):
    """Release stale coding allocations older than the configured timeout."""
    from app.services.coding_allocation_service import (
        release_stale_coding_allocations,
        release_stale_reviewer_allocations,
    )
    from app.services.coder_workflow_service import (
        mark_reviewer_eligible_after_recode_window_submissions,
    )

    released = release_stale_coding_allocations(timeout_hours=1)
    reviewer_released = release_stale_reviewer_allocations(timeout_hours=1)
    reviewer_eligible = mark_reviewer_eligible_after_recode_window_submissions()
    return {
        "released": released,
        "reviewer_released": reviewer_released,
        "reviewer_eligible": reviewer_eligible,
    }


def ensure_coding_timeout_cleanup_scheduled():
    """Seed the stale coding allocation cleanup task (every 1 hour). Idempotent."""
    try:
        from app import db

        with db.engine.begin() as conn:
            interval_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_intervalschedule "
                    "WHERE every = 1 AND period = 'hours' LIMIT 1"
                )
            ).scalar()
            if interval_id is None:
                interval_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_intervalschedule (every, period) "
                        "VALUES (1, 'hours') RETURNING id"
                    )
                ).scalar()

            exists = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_periodictask WHERE name = :name LIMIT 1"
                ),
                {"name": "Release stale coding allocations — every 1 hour"},
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
                        "name": "Release stale coding allocations — every 1 hour",
                        "task": "app.tasks.sync_tasks.release_stale_coding_allocations_task",
                        "schedule_id": interval_id,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )

        log.info("Coding allocation cleanup beat schedule seeded: every 1 hour.")
    except Exception as e:
        log.warning("Could not seed coding allocation cleanup schedule: %s", e)


@shared_task(
    name="app.tasks.sync_tasks.cleanup_expired_demo_coding_task",
    bind=True,
    soft_time_limit=120,
    time_limit=240,
)
def cleanup_expired_demo_coding_task(self):
    """Deactivate expired demo-coding artifacts and return forms to the ready pool."""
    from app.services.coding_allocation_service import cleanup_expired_demo_coding_artifacts

    expired = cleanup_expired_demo_coding_artifacts()
    return {"expired_demo_artifacts": expired}


def ensure_demo_cleanup_scheduled():
    """Seed the demo coding artifact cleanup task (every 15 minutes). Idempotent."""
    try:
        from app import db

        with db.engine.begin() as conn:
            interval_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_intervalschedule "
                    "WHERE every = 15 AND period = 'minutes' LIMIT 1"
                )
            ).scalar()
            if interval_id is None:
                interval_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_intervalschedule (every, period) "
                        "VALUES (15, 'minutes') RETURNING id"
                    )
                ).scalar()

            exists = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_periodictask WHERE name = :name LIMIT 1"
                ),
                {"name": "Demo coding cleanup — every 15 minutes"},
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
                        "name": "Demo coding cleanup — every 15 minutes",
                        "task": "app.tasks.sync_tasks.cleanup_expired_demo_coding_task",
                        "schedule_id": interval_id,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )

        log.info("Demo coding cleanup beat schedule seeded: every 15 minutes.")
    except Exception as e:
        log.warning("Could not seed demo coding cleanup schedule: %s", e)


def ensure_submission_analytics_mv_refresh_scheduled():
    """Seed the submission analytics MV refresh task (every 1 hour). Idempotent."""
    try:
        from app import db

        with db.engine.begin() as conn:
            interval_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_intervalschedule "
                    "WHERE every = 1 AND period = 'hours' LIMIT 1"
                )
            ).scalar()
            if interval_id is None:
                interval_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_intervalschedule (every, period) "
                        "VALUES (1, 'hours') RETURNING id"
                    )
                ).scalar()

            exists = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_periodictask WHERE name = :name LIMIT 1"
                ),
                {"name": "Submission analytics MV refresh — every 1 hour"},
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
                        "name": "Submission analytics MV refresh — every 1 hour",
                        "task": "app.tasks.sync_tasks.refresh_submission_analytics_mv_task",
                        "schedule_id": interval_id,
                    },
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_periodictaskchanged (last_update) "
                        "VALUES (NOW()) ON CONFLICT DO NOTHING"
                    )
                )

        log.info("Submission analytics MV refresh beat schedule seeded: every 1 hour.")
    except Exception as e:
        log.warning("Could not seed submission analytics MV refresh schedule: %s", e)
