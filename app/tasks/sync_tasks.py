"""Celery tasks for ODK data sync.

The run_odk_sync task wraps va_data_sync_odkcentral(), recording every run
in va_sync_runs so the admin dashboard can show history and current status.
"""
import json
import logging
import sqlalchemy as sa
from celery import chord, shared_task
from datetime import datetime, timezone

log = logging.getLogger(__name__)
ANALYTICS_MV_TRIGGER = "analytics_mv"
ATTACHMENT_SYNC_BATCH_SIZE = 50


def _get_single_form_odk_client(va_form):
    """Return one pyODK client for the single-form sync run."""
    from app.utils import va_odk_clientsetup

    return va_odk_clientsetup(project_id=va_form.project_id)


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


def _schedule_attachment_sync_for_form(run_id, form_id: str, upserted_map: dict[str, str], log_progress) -> None:
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    items = list(upserted_map.items())
    batches = [
        dict(items[i:i + ATTACHMENT_SYNC_BATCH_SIZE])
        for i in range(0, len(items), ATTACHMENT_SYNC_BATCH_SIZE)
    ]
    if not batches:
        return

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == run_id).with_for_update()
    ).scalar_one()
    run.attachment_forms_total = (run.attachment_forms_total or 0) + 1
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
    header = [
        run_attachment_sync_batch.s(
            form_id=form_id,
            batch_map=batch,
            run_id=str(run_id),
        )
        for batch in batches
    ]
    callback = finalize_form_attachment_sync.s(
        form_id=form_id,
        va_sids=list(upserted_map.keys()),
        run_id=str(run_id),
    )
    chord(header)(callback)


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

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        def dispatch_attachments(va_form, upserted_map, _media_dir, progress_callback):
            _schedule_attachment_sync_for_form(
                run_id,
                va_form.form_id,
                upserted_map,
                progress_callback,
            )

        result = va_data_sync_odkcentral(
            log_progress=log_progress,
            attachment_sync_dispatcher=dispatch_attachments,
        )
        run = db.session.get(VaSyncRun, run_id)
        failed_forms = result.get("failed_forms", []) if result else []
        if result:
            run.records_added = result.get("added", 0)
            run.records_updated = result.get("updated", 0)
            run.smartva_records_generated = result.get("smartva_updated", 0)
        if failed_forms:
            _append_run_error(run, f"Failed forms: {', '.join(failed_forms)}")
        if result and result.get("attachment_sync_forms_enqueued", 0):
            run.status = "running"
        else:
            run.status = "partial" if failed_forms else "success"
            run.finished_at = datetime.now(timezone.utc)
        db.session.commit()

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
        _attach_all_odk_comments,
        _finalize_enriched_submissions_for_form,
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
        amended_sids: set[str] = set()
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
            amended_sids,
            upserted_map,
            enrich_payloads=False,
            defer_protected_updates=True,
        )
        db.session.commit()
        log_progress(
            f"[{form_id}] upsert: complete — +{added} added, {updated} updated"
            + (f", {skipped} skipped" if skipped else "")
        )
        if upserted_map:
            log_progress(
                f"[{form_id}] enrich: adding ODK review comments to "
                f"{len(va_submissions_raw)} submission(s)…"
            )
            va_submissions_raw = _attach_all_odk_comments(
                va_form,
                va_submissions_raw,
                client=odk_client,
                log_progress=log_progress,
            )
            log_progress(
                f"[{form_id}] enrich: review comments added for "
                f"{len(va_submissions_raw)} submission(s)"
            )
            log_progress(
                f"[{form_id}] enrich: enriching submission metadata…"
            )
            enriched_count = _finalize_enriched_submissions_for_form(
                va_form,
                va_submissions_raw,
                upserted_map,
                amended_sids,
                client=odk_client,
                log_progress=log_progress,
            )
            db.session.commit()
            log_progress(
                f"[{form_id}] enrich: complete — metadata enriched for "
                f"{enriched_count} submission(s)"
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
        if upserted_map:
            db.session.commit()
            _schedule_attachment_sync_for_form(run_id, form_id, upserted_map, log_progress)
            run = db.session.get(VaSyncRun, run_id)
            run.status = "running"
        else:
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        log.info("SingleFormSync [%s]: queued attachment sync — added=%d updated=%d", form_id, added, updated)

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
    name="app.tasks.sync_tasks.run_attachment_sync_batch",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def run_attachment_sync_batch(self, *, form_id: str, batch_map: dict[str, str], run_id: str):
    """Sync one bounded attachment batch for a form."""
    import os
    from flask import current_app
    from app import db
    from app.models.va_forms import VaForms
    from app.utils import va_odk_sync_form_attachments

    va_form = db.session.get(VaForms, form_id)
    if va_form is None:
        return {
            "downloaded": 0,
            "skipped": 0,
            "errors": len(batch_map or {}),
            "error_message": f"Form '{form_id}' not found for attachment batch.",
        }

    form_dir = os.path.join(current_app.config["APP_DATA"], form_id)
    media_dir = os.path.join(form_dir, "media")
    os.makedirs(media_dir, exist_ok=True)
    try:
        totals = va_odk_sync_form_attachments(
            va_form,
            batch_map or {},
            media_dir,
            client_factory=lambda: _get_single_form_odk_client(va_form),
        )
        db.session.commit()
        _log_progress(
            db,
            run_id,
            (
                f"[{form_id}] attachments: batch complete — "
                f"{totals['downloaded']} downloaded, "
                f"{totals['skipped']} skipped"
                + (f", {totals['errors']} errors" if totals["errors"] else "")
            ),
        )
        return {
            "downloaded": totals["downloaded"],
            "skipped": totals["skipped"],
            "errors": totals["errors"],
            "error_message": None,
        }
    except Exception as exc:
        db.session.rollback()
        _log_progress(db, run_id, f"[{form_id}] attachments: batch FAILED — {exc}")
        return {
            "downloaded": 0,
            "skipped": 0,
            "errors": len(batch_map or {}),
            "error_message": str(exc)[:500],
        }


@shared_task(
    name="app.tasks.sync_tasks.finalize_form_attachment_sync",
    bind=True,
    soft_time_limit=900,
    time_limit=1800,
)
def finalize_form_attachment_sync(self, results, *, form_id: str, va_sids: list[str], run_id: str):
    """Finalize all attachment batches for one form, then run SmartVA."""
    from uuid import UUID
    from app import db
    from app.models.va_forms import VaForms
    from app.models.va_sync_runs import VaSyncRun
    from app.services import smartva_service
    from app.services.workflow.definition import WORKFLOW_ATTACHMENT_SYNC_PENDING
    from app.services.workflow.state_store import get_submission_workflow_state
    from app.services.workflow.transitions import (
        WorkflowTransitionError,
        mark_attachment_sync_completed,
        system_actor,
    )

    downloaded = sum(int((row or {}).get("downloaded", 0)) for row in results or [])
    skipped = sum(int((row or {}).get("skipped", 0)) for row in results or [])
    errors = sum(int((row or {}).get("errors", 0)) for row in results or [])
    error_messages = [
        (row or {}).get("error_message")
        for row in results or []
        if (row or {}).get("error_message")
    ]

    _log_progress(
        db,
        run_id,
        (
            f"[{form_id}] attachments: complete — {downloaded} downloaded, "
            f"{skipped} skipped"
            + (f", {errors} errors" if errors else "")
        ),
    )

    transitioned_count = 0
    for va_sid in va_sids:
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
            error_messages.append(f"{va_sid}: {exc}")
    db.session.commit()
    _log_progress(
        db,
        run_id,
        f"[{form_id}] workflow: attachments finished for {transitioned_count} "
        f"submission(s); ready for SmartVA",
    )

    smartva_updated = 0
    va_form = db.session.get(VaForms, form_id)
    if va_form is not None:
        try:
            _log_progress(
                db,
                run_id,
                f"SmartVA {form_id}: starting after attachments finished.",
            )
            smartva_updated = smartva_service.generate_for_form(
                va_form,
                amended_sids=set(va_sids),
                log_progress=lambda msg: _log_progress(db, run_id, msg),
            )
            _log_progress(
                db,
                run_id,
                f"SmartVA {form_id}: finished — {smartva_updated} result(s) generated.",
            )
        except Exception as exc:
            db.session.rollback()
            error_messages.append(f"SmartVA {form_id}: {exc}")
            _log_progress(db, run_id, f"SmartVA {form_id}: FAILED — {exc}")

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(run_id)).with_for_update()
    ).scalar_one_or_none()
    if run is None:
        return

    run.attachment_forms_completed = (run.attachment_forms_completed or 0) + 1
    run.attachment_downloaded = (run.attachment_downloaded or 0) + downloaded
    run.attachment_skipped = (run.attachment_skipped or 0) + skipped
    run.attachment_errors = (run.attachment_errors or 0) + errors
    run.smartva_records_generated = (run.smartva_records_generated or 0) + smartva_updated
    for message in error_messages:
        _append_run_error(run, message)
    _log_progress(
        db,
        run_id,
        (
            f"[{form_id}] pipeline: complete — "
            f"{downloaded} attachments downloaded, "
            f"{smartva_updated} SmartVA result(s) generated"
            + (f", {errors} attachment error(s)" if errors else "")
        ),
    )

    if (run.attachment_forms_completed or 0) >= (run.attachment_forms_total or 0):
        run.finished_at = datetime.now(timezone.utc)
        run.status = "partial" if run.error_message or (run.attachment_errors or 0) else "success"
        _log_progress(
            db,
            run_id,
            (
                "Sync finished: "
                f"{run.records_added or 0} added, "
                f"{run.records_updated or 0} updated, "
                f"{run.attachment_downloaded or 0} attachments downloaded, "
                f"{run.smartva_records_generated or 0} SmartVA result(s) generated."
            ),
        )

    db.session.commit()


@shared_task(
    name="app.tasks.sync_tasks.run_attachment_cache_backfill",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_attachment_cache_backfill(
    self,
    *,
    project_id: str | None = None,
    site_id: str | None = None,
    form_id: str | None = None,
    triggered_by: str = "attach_backfill",
    user_id=None,
):
    """Backfill attachment cache rows from existing local media files."""
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services.attachment_cache_backfill_service import backfill_attachment_cache

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

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        result = backfill_attachment_cache(
            project_id=project_id,
            site_id=site_id,
            form_id=form_id,
            log_progress=log_progress,
        )
        run = db.session.get(VaSyncRun, run_id)
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        run.records_added = result.get("attachments_created", 0)
        run.records_updated = result.get("attachments_updated", 0)
        db.session.commit()
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
        _attach_all_odk_comments,
        _finalize_enriched_submissions_for_form,
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
                f"[{va_form.form_id}] enrich: adding ODK review comments to "
                f"{len(records)} submission(s)…"
            )
            records = _attach_all_odk_comments(
                va_form,
                records,
                client=odk_client,
                log_progress=log_progress,
            )
            log_progress(
                f"[{va_form.form_id}] enrich: review comments added for "
                f"{len(records)} submission(s)"
            )
            log_progress(
                f"[{va_form.form_id}] enrich: enriching submission metadata…"
            )
            enriched_count = _finalize_enriched_submissions_for_form(
                va_form,
                records,
                upserted_map,
                amended_sids=set(),
                client=odk_client,
                log_progress=log_progress,
            )
            db.session.commit()
            log_progress(
                f"[{va_form.form_id}] enrich: complete — metadata enriched for "
                f"{enriched_count} submission(s)"
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
            _schedule_attachment_sync_for_form(run_id, va_form.form_id, upserted_map, log_progress)
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
        log.warning("SmartVA task [%s]: failed — %s", va_sid, exc, exc_info=True)
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

        print("Sync beat schedule seeded: every 6 hours.")
    except Exception as e:
        print(f"Warning: Could not seed sync schedule: {e}")


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
    """Refresh the submission analytics materialized view and record the run."""
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
        _log_progress(db, run_id, "Refreshing submission analytics materialized view.")
        refresh_submission_analytics_mv(concurrently=True)
        run = db.session.get(VaSyncRun, run_id)
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        run.records_updated = db.session.scalar(
            sa.text("SELECT COUNT(*) FROM public.va_submission_analytics_mv")
        )
        db.session.commit()
        _log_progress(
            db,
            run_id,
            f"Submission analytics materialized view refreshed: {run.records_updated} rows.",
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

        print("Coding allocation cleanup beat schedule seeded: every 1 hour.")
    except Exception as e:
        print(f"Warning: Could not seed coding allocation cleanup schedule: {e}")


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

        print("Submission analytics MV refresh beat schedule seeded: every 1 hour.")
    except Exception as e:
        print(f"Warning: Could not seed submission analytics MV refresh schedule: {e}")
