"""Celery tasks for ODK data sync.

The run_odk_sync task wraps va_data_sync_odkcentral(), recording every run
in va_sync_runs so the admin dashboard can show history and current status.
"""
import json
import logging
import sqlalchemy as sa
from celery import shared_task
from datetime import datetime, timezone

log = logging.getLogger(__name__)
ANALYTICS_MV_TRIGGER = "analytics_mv"


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
        result = va_data_sync_odkcentral(log_progress=log_progress)
        run = db.session.get(VaSyncRun, run_id)
        failed_forms = result.get("failed_forms", []) if result else []
        run.status = "partial" if failed_forms else "success"
        run.finished_at = datetime.now(timezone.utc)
        if result:
            run.records_added = result.get("added", 0)
            run.records_updated = result.get("updated", 0)
        if failed_forms:
            run.error_message = f"Failed forms: {', '.join(failed_forms)}"
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
        va_odk_sync_form_attachments,
    )
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _mark_form_sync_issues, _upsert_form_submissions,
        SYNC_ISSUE_MISSING_IN_ODK,
    )
    from app.models import VaStatuses, VaSubmissionsAuditlog, VaSubmissions

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
        log_progress(f"[{form_id}] fetching all submissions from ODK…")
        va_submissions_raw = va_odk_fetch_submissions(
            va_form,
            since=None,
            client=odk_client,
        )
        # Upsert
        upserted_map: dict[str, str] = {}
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form, va_submissions_raw, amended_sids, upserted_map
        )
        db.session.commit()
        log_progress(
            f"[{form_id}] upserted: +{added} added, {updated} updated"
            + (f", {skipped} skipped" if skipped else "")
        )

        # Sync attachments for upserted submissions
        if upserted_map:
            attachment_totals = va_odk_sync_form_attachments(
                va_form,
                upserted_map,
                media_dir,
                client_factory=lambda: _get_single_form_odk_client(va_form),
            )
            db.session.commit()
            log_progress(
                f"[{form_id}] attachments: "
                f"{attachment_totals['downloaded']} downloaded, "
                f"{attachment_totals['skipped']} skipped"
                + (
                    f", {attachment_totals['errors']} errors"
                    if attachment_totals["errors"]
                    else ""
                )
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

        # SmartVA
        from app.services import smartva_service
        smartva_updated = smartva_service.generate_for_form(
            va_form,
            amended_sids=amended_sids,
            log_progress=log_progress,
        )

        run = db.session.get(VaSyncRun, run_id)
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        run.records_added = added
        run.records_updated = updated
        db.session.commit()
        log.info("SingleFormSync [%s]: complete — added=%d updated=%d smartva=%d", form_id, added, updated, smartva_updated)

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
        va_odk_sync_form_attachments,
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
        log_progress(f"[{va_sid}] fetching latest submission from ODK…")
        records = va_odk_fetch_submissions_by_ids(
            va_form,
            [instance_id],
            client=odk_client,
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
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form,
            records,
            amended_sids=set(),
            upserted_map=upserted_map,
        )
        _mark_form_sync_issues(va_form, va_odk_fetch_instance_ids(va_form, client=odk_client))
        db.session.commit()

        form_dir = os.path.join(current_app.config["APP_DATA"], va_form.form_id)
        media_dir = os.path.join(form_dir, "media")
        os.makedirs(media_dir, exist_ok=True)
        if upserted_map:
            va_odk_sync_form_attachments(
                va_form,
                upserted_map,
                media_dir,
                client_factory=lambda: _get_single_form_odk_client(va_form),
            )
            db.session.commit()
        from app.services import smartva_service
        smartva_updated = smartva_service.generate_for_submission(
            va_sid, log_progress=log_progress
        )

        run = db.session.get(VaSyncRun, run_id)
        run.status = "success"
        run.finished_at = _dt.now(timezone.utc)
        run.records_added = added
        run.records_updated = updated
        db.session.commit()
        log_progress(
            f"[{va_sid}] refreshed from ODK: +{added} added, {updated} updated"
            + (f", {discarded} discarded" if discarded else "")
            + (f", {skipped} skipped" if skipped else "")
            + (f", {smartva_updated} smartva" if smartva_updated else "")
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
