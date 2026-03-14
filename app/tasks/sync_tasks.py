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
        va_odk_fetch_submissions,
        va_odk_write_form_csv,
        va_odk_rebuild_form_csv_from_db,
        va_odk_sync_submission_attachments,
        va_smartva_prepdata,
        va_smartva_runsmartva,
        va_smartva_formatsmartvaresult,
        va_smartva_appendsmartvaresults,
    )
    from app.services.va_data_sync.va_data_sync_01_odkcentral import (
        _upsert_form_submissions, _pending_smartva_sids,
    )
    from app.models import VaStatuses, VaSmartvaResults, VaSubmissionsAuditlog, VaSubmissions
    import uuid

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

        log_progress(f"[{form_id}] force-resync started — bypassing delta check")
        log.info("SingleFormSync [%s]: force-resync started.", form_id)

        snapshot_time = datetime.now(timezone.utc)
        amended_sids: set[str] = set()
        form_dir = os.path.join(current_app.config["APP_DATA"], form_id)
        media_dir = os.path.join(form_dir, "media")
        os.makedirs(media_dir, exist_ok=True)

        # Fetch ALL submissions (force-resync = no since filter)
        log_progress(f"[{form_id}] fetching all submissions from ODK…")
        va_submissions_raw = va_odk_fetch_submissions(va_form, since=None)
        va_odk_write_form_csv(va_submissions_raw, va_form, form_dir)

        # Upsert
        upserted_map: dict[str, str] = {}
        added, updated, discarded = _upsert_form_submissions(
            va_form, va_submissions_raw, amended_sids, upserted_map
        )
        db.session.commit()
        log_progress(f"[{form_id}] upserted: +{added} added, {updated} updated")

        # Sync attachments for upserted submissions
        if upserted_map:
            attach_dl = attach_skip = attach_err = 0
            for va_sid, instance_id in upserted_map.items():
                if not instance_id:
                    continue
                try:
                    r = va_odk_sync_submission_attachments(va_form, instance_id, va_sid, media_dir)
                    attach_dl += r["downloaded"]
                    attach_skip += r["skipped"]
                    attach_err += r["errors"]
                except Exception as ae:
                    attach_err += 1
                    log.warning("SingleFormSync [%s] attachment error for %s: %s", form_id, va_sid, ae)
            db.session.commit()
            log_progress(
                f"[{form_id}] attachments: {attach_dl} downloaded, {attach_skip} skipped"
                + (f", {attach_err} errors" if attach_err else "")
            )

        # Rebuild full CSV from DB
        va_odk_rebuild_form_csv_from_db(va_form, form_dir)

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
        pending = _pending_smartva_sids(form_id) | (
            amended_sids & set(
                db.session.scalars(
                    sa.select(VaSubmissions.va_sid).where(
                        VaSubmissions.va_form_id == form_id
                    )
                ).all()
            )
        )
        smartva_updated = 0
        if pending:
            log_progress(f"SmartVA {form_id}: preparing input ({len(pending)} pending)…")
            va_smartva_prepdata(va_form, pending_sids=pending)
            va_smartva_runsmartva(va_form)
            output_file = va_smartva_formatsmartvaresult(va_form)
            if output_file:
                va_smartva_new_results, va_smartva_existingactive_results = (
                    va_smartva_appendsmartvaresults(db.session, {va_form: output_file})
                )
                if va_smartva_new_results is not None:
                    for va_smartva_record in va_smartva_new_results.itertuples():
                        va_sid = getattr(va_smartva_record, "sid", None)
                        va_smartva_existing = va_smartva_existingactive_results.get(va_sid)
                        if va_sid not in amended_sids and va_smartva_existing:
                            continue
                        if va_smartva_existing:
                            va_smartva_existing.va_smartva_status = VaStatuses.deactive
                            db.session.add(VaSubmissionsAuditlog(
                                va_sid=va_sid,
                                va_audit_entityid=va_smartva_existing.va_smartva_id,
                                va_audit_byrole="vaadmin",
                                va_audit_operation="d",
                                va_audit_action="va_smartva_deletion_during_datasync",
                            ))
                        va_smartva_uuid = uuid.uuid4()
                        db.session.add(VaSmartvaResults(
                            va_smartva_id=va_smartva_uuid,
                            va_sid=va_sid,
                            va_smartva_age=(
                                format(float(getattr(va_smartva_record, "age", None)), ".1f")
                                if getattr(va_smartva_record, "age", None) is not None
                                else None
                            ),
                            va_smartva_gender=getattr(va_smartva_record, "sex", None),
                            va_smartva_cause1=getattr(va_smartva_record, "cause1", None),
                            va_smartva_likelihood1=getattr(va_smartva_record, "likelihood1", None),
                            va_smartva_keysymptom1=getattr(va_smartva_record, "key_symptom1", None),
                            va_smartva_cause2=getattr(va_smartva_record, "cause2", None),
                            va_smartva_likelihood2=getattr(va_smartva_record, "likelihood2", None),
                            va_smartva_keysymptom2=getattr(va_smartva_record, "key_symptom2", None),
                            va_smartva_cause3=getattr(va_smartva_record, "cause3", None),
                            va_smartva_likelihood3=getattr(va_smartva_record, "likelihood3", None),
                            va_smartva_keysymptom3=getattr(va_smartva_record, "key_symptom3", None),
                            va_smartva_allsymptoms=getattr(va_smartva_record, "all_symptoms", None),
                            va_smartva_resultfor=getattr(va_smartva_record, "result_for", None),
                            va_smartva_cause1icd=getattr(va_smartva_record, "cause1_icd", None),
                            va_smartva_cause2icd=getattr(va_smartva_record, "cause2_icd", None),
                            va_smartva_cause3icd=getattr(va_smartva_record, "cause3_icd", None),
                        ))
                        db.session.add(VaSubmissionsAuditlog(
                            va_sid=va_sid,
                            va_audit_entityid=va_smartva_uuid,
                            va_audit_byrole="vaadmin",
                            va_audit_operation="c",
                            va_audit_action="va_smartva_creation_during_datasync",
                        ))
                        smartva_updated += 1
                    db.session.commit()
            log_progress(f"SmartVA {form_id}: {smartva_updated} result(s) saved.")
        else:
            log_progress(f"SmartVA {form_id}: all results up to date, skipping.")

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
    """Mark orphaned 'running' rows as 'error' on worker startup."""
    try:
        from app import db
        db.session.execute(sa.text("""
            UPDATE va_sync_runs
            SET status = 'error',
                finished_at = NOW(),
                error_message = 'Worker restarted — run did not complete'
            WHERE status = 'running'
              AND started_at < NOW() - INTERVAL '2 hours'
        """))
        db.session.commit()
    except Exception as e:
        print(f"Warning: Could not clean up stale sync runs: {e}")


@shared_task(
    name="app.tasks.sync_tasks.release_stale_coding_allocations_task",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
)
def release_stale_coding_allocations_task(self):
    """Release stale coding allocations older than the configured timeout."""
    from app.services.coding_allocation_service import release_stale_coding_allocations

    return {"released": release_stale_coding_allocations(timeout_hours=1)}


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
