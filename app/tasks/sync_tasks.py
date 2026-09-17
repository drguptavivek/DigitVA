"""Celery tasks for ODK data sync.

The run_odk_sync task wraps va_data_sync_odkcentral(), recording every run
in va_sync_runs so the admin dashboard can show history and current status.
"""
import json
import logging
import os
import traceback
import uuid
from contextlib import contextmanager

import sqlalchemy as sa
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from datetime import datetime, timezone

from app.services.attachment_service import (
    QUARANTINE_TRIGGER,
    S3_UPLOAD_TRIGGER,
    attachment_state_by_submission,
)

log = get_task_logger(__name__)
ANALYTICS_MV_TRIGGER = "analytics_mv"
ENRICHMENT_SYNC_BATCH_SIZE = 5
# Most attachment gaps are closed by the sync download above; this is the
# bounded second pass that rebuilds what only ODK Central can supply (a lost
# store object, a stale or failed MP3 derivative).
ATTACHMENT_REPAIR_BATCH_LIMIT = 50
# Run directories archived per press of the admin "Archive pending runs" button
# (and per scheduled sweep). Bounded so one job cannot run for hours: a backlog
# is cleared by repeated presses.
SMARTVA_ARCHIVE_TASK_LIMIT = 200
# Attachment rows copied into the bucket per sweep of run_attachment_s3_upload
# (and per press of the panel button). Bounded so one sweep cannot run for
# hours; a larger backlog is cleared by the next sweep ten minutes later.
ATTACHMENT_S3_UPLOAD_TASK_LIMIT = 500
# Sweeps are serialised on this key so a scheduled sweep and an admin press
# never work the same rows at the same time. Longer than the task's hard time
# limit, so a worker killed mid-sweep still releases it by expiry.
ATTACHMENT_S3_UPLOAD_LOCK_KEY = "digitva:lock:attachment-s3-upload"
ATTACHMENT_S3_UPLOAD_LOCK_TTL_SECONDS = 4200
# The beat row's name, and its identity: seeding looks the row up by name, so
# renaming it here creates a second schedule rather than moving this one. The
# interval is configuration, so it is not in the name.
ATTACHMENT_S3_UPLOAD_SCHEDULE_NAME = "Attachment S3 upload sweep"
DEFAULT_ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES = 10
INTERRUPTED_RUN_MESSAGE = (
    "Interrupted run — the worker stopped before completion. "
    "Re-initiate Sync or Repair to continue remaining gaps."
)


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
                "payload_revalidated": bool(value.get("payload_revalidated")),
                "legacy_attachment_rows": int(value.get("legacy_attachment_rows") or 0),
            }
        else:
            normalized[va_sid] = {
                "instance_id": value or "",
                "needs_metadata": True,
                "needs_attachments": True,
                "needs_smartva": True,
                "payload_revalidated": False,
                "legacy_attachment_rows": 0,
            }
    return normalized


def _batch_stage_counts(batch_plan: dict[str, dict]) -> dict[str, int]:
    """Return counts of submissions needing each stage in a batch plan."""
    return {
        "metadata": sum(1 for item in batch_plan.values() if item.get("needs_metadata")),
        "attachments": sum(1 for item in batch_plan.values() if item.get("needs_attachments")),
        "smartva": sum(1 for item in batch_plan.values() if item.get("needs_smartva")),
    }


def _legacy_attachment_rows_by_submission(
    form_id: str,
    *,
    target_sids: list[str] | None = None,
) -> dict[str, int]:
    """Return counts of attachment rows that still lack opaque storage names."""
    from app import db
    from app.models import VaSubmissions, VaSubmissionAttachments

    stmt = (
        sa.select(
            VaSubmissionAttachments.va_sid,
            sa.func.count().label("legacy_count"),
        )
        .select_from(VaSubmissionAttachments)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == form_id,
            VaSubmissionAttachments.exists_on_odk.is_(True),
            VaSubmissionAttachments.storage_name.is_(None),
        )
        .group_by(VaSubmissionAttachments.va_sid)
    )
    if target_sids:
        stmt = stmt.where(VaSubmissionAttachments.va_sid.in_(target_sids))

    return {
        row["va_sid"]: int(row["legacy_count"] or 0)
        for row in db.session.execute(stmt).mappings().all()
    }


def _refresh_batch_plan_after_enrichment(
    *,
    form_id: str,
    batch_plan: dict[str, dict],
    raw_submissions: list[dict],
    upserted_map: dict[str, str],
) -> tuple[dict[str, dict], dict[str, int], int]:
    """Re-evaluate repair needs after metadata enrichment updates local state."""
    from app.services.workflow.definition import WORKFLOW_FINALIZED_UPSTREAM_CHANGED
    from app.services.workflow.state_store import get_submission_workflow_state

    refreshed_plan = _normalize_batch_plan(batch_plan)
    repair_map, summary = _build_repair_map_for_form(
        form_id,
        raw_submissions,
        {},
    )
    upstream_changed_count = 0
    for va_sid, item in refreshed_plan.items():
        item["needs_metadata"] = False
        item["payload_revalidated"] = True
        if get_submission_workflow_state(va_sid) == WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
            item["needs_attachments"] = False
            item["needs_smartva"] = False
            upstream_changed_count += 1
            continue
        recalculated = repair_map.get(va_sid)
        if recalculated is None:
            item["needs_attachments"] = False
            item["needs_smartva"] = False
            continue
        item["instance_id"] = recalculated.get("instance_id") or item.get("instance_id") or ""
        item["needs_attachments"] = bool(recalculated.get("needs_attachments"))
        item["needs_smartva"] = bool(recalculated.get("needs_smartva"))
    return refreshed_plan, summary, upstream_changed_count

def _get_single_form_odk_client(va_form):
    """Return one pyODK client for the single-form sync run."""
    from app.utils import va_odk_clientsetup
    from app.services.runtime_form_sync_service import get_active_mapping_for_form

    mapping = get_active_mapping_for_form(va_form)
    if mapping is None:
        raise ValueError(
            f"Active runtime mapping not found for form '{va_form.form_id}'."
        )

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


def _repair_batch_attachments(
    *,
    sids_by_form: dict[str, list[str]],
    log_progress,
    label: str,
    batch_index: int,
    batch_total: int,
) -> dict[str, int]:
    """Second attachment pass for one repair batch, through the attachment service.

    The sync download above restores anything Central still lists normally.
    What is left — a store object that went missing, an MP3 derivative that is
    stale or failed to convert — can only be rebuilt from the original, which
    is exactly what ``attachment_service.repair_attachment()`` does. Bounded by
    ``ATTACHMENT_REPAIR_BATCH_LIMIT`` per form so one bad form cannot stretch a
    batch, and the run's progress log records outcome counts only: no
    filenames, no submission identifiers, no URLs.
    """
    from app import db
    from app.services import attachment_service

    outcomes: dict[str, int] = {}
    for form_id, form_sids in sorted(sids_by_form.items()):
        try:
            candidates = attachment_service.repair_candidates(
                form_id,
                target_sids=form_sids,
                limit=ATTACHMENT_REPAIR_BATCH_LIMIT,
            )
        except Exception:
            log.warning(
                "Attachment repair candidates failed for %s", form_id, exc_info=True
            )
            continue
        for record in candidates:
            try:
                outcome = attachment_service.repair_attachment(record)
            except Exception:
                db.session.rollback()
                log.warning(
                    "Attachment repair failed for form %s", form_id, exc_info=True
                )
                outcomes[attachment_service.REPAIR_ERROR] = (
                    outcomes.get(attachment_service.REPAIR_ERROR, 0) + 1
                )
                continue
            outcomes[outcome.outcome] = outcomes.get(outcome.outcome, 0) + 1

    if outcomes:
        summary = ", ".join(f"{name}={count}" for name, count in sorted(outcomes.items()))
        log_progress(
            f"[{label}] attachment repair: batch {batch_index}/{batch_total} — {summary}"
        )
    return outcomes


def _run_canonical_repair_batches(
    *,
    run_id,
    label: str,
    candidate_sids: list[str],
    trigger_source: str,
    force_attachment_redownload: bool,
    log_progress,
    finalize_run_on_completion: bool = True,
    count_total_on_entry: bool = True,
) -> dict[str, int]:
    """Run the canonical per-submission repair engine across bounded batches."""
    from uuid import UUID
    from app import db
    from app.models import VaForms
    from app.models.va_sync_runs import VaSyncRun
    from app.services import attachment_service, smartva_service
    from app.services.open_submission_repair_service import (
        repair_submission_current_payload,
    )

    unique_candidate_sids = list(dict.fromkeys(candidate_sids))
    if not unique_candidate_sids:
        return {
            "downloaded": 0,
            "non_audit_downloaded": 0,
            "audit_downloaded": 0,
            "smartva_generated": 0,
            "errors": 0,
            "skipped": 0,
            "held": 0,
        }

    batches = [
        unique_candidate_sids[i:i + ENRICHMENT_SYNC_BATCH_SIZE]
        for i in range(0, len(unique_candidate_sids), ENRICHMENT_SYNC_BATCH_SIZE)
    ]

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(str(run_id))).with_for_update()
    ).scalar_one_or_none()
    if run is None:
        return {
            "downloaded": 0,
            "non_audit_downloaded": 0,
            "audit_downloaded": 0,
            "smartva_generated": 0,
            "errors": 0,
            "skipped": 0,
            "held": 0,
        }

    if count_total_on_entry:
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
        f"[{label}] pipeline: queued {len(batches)} repair batch(es) "
        f"for {len(unique_candidate_sids)} submission(s)…"
    )

    totals = {
        "downloaded": 0,
        "non_audit_downloaded": 0,
        "audit_downloaded": 0,
        "smartva_generated": 0,
        "errors": 0,
        "skipped": 0,
        "held": 0,
    }
    batch_total = len(batches)

    for batch_index, batch_sids in enumerate(batches, start=1):
        if _is_run_cancelled(run_id=run_id):
            db.session.rollback()
            log_progress(
                f"[{label}] pipeline: parent run cancelled; "
                f"stopping remaining repair batches at {batch_index}/{batch_total}."
            )
            return totals

        log_progress(
            f"[{label}] repair: batch {batch_index}/{batch_total} "
            f"starting for {len(batch_sids)} submission(s)…"
        )
        batch_downloaded = 0
        batch_non_audit_downloaded = 0
        batch_audit_downloaded = 0
        batch_smartva_generated = 0
        batch_errors = 0
        batch_skipped = 0
        batch_held = 0
        error_messages: list[str] = []
        smartva_sids_by_form: dict[str, set[str]] = {}
        sids_by_form: dict[str, list[str]] = {}

        for va_sid in batch_sids:
            try:
                result = repair_submission_current_payload(
                    va_sid,
                    trigger_source=trigger_source,
                    force_attachment_redownload=force_attachment_redownload,
                    run_smartva=False,
                )
            except Exception as exc:
                batch_errors += 1
                error_messages.append(f"{va_sid}: {exc}")
                continue

            initial_summary = result.get("initial_summary") or {}
            attachments_missing = int(initial_summary.get("attachments_missing", 0) or 0)
            downloaded = int(result.get("attachments_downloaded", 0) or 0)
            non_audit_downloaded = int(result.get("non_audit_downloaded", 0) or 0)
            audit_downloaded = int(result.get("audit_downloaded", 0) or 0)
            smartva_generated = int(result.get("smartva_generated", 0) or 0)
            upstream_changed_held = bool(result.get("upstream_changed_held"))
            needs_smartva_after_repair = bool(result.get("needs_smartva_after_repair"))
            form_id = result.get("form_id")
            if isinstance(form_id, str) and form_id:
                sids_by_form.setdefault(form_id, []).append(va_sid)

            batch_downloaded += downloaded
            batch_non_audit_downloaded += non_audit_downloaded
            batch_audit_downloaded += audit_downloaded
            batch_smartva_generated += smartva_generated
            if attachments_missing > 0 and downloaded == 0 and not upstream_changed_held:
                batch_skipped += 1
            if upstream_changed_held:
                batch_held += 1
            if (
                not upstream_changed_held
                and needs_smartva_after_repair
                and isinstance(form_id, str)
                and form_id
            ):
                smartva_sids_by_form.setdefault(form_id, set()).add(va_sid)

        batch_repair_outcomes = _repair_batch_attachments(
            sids_by_form=sids_by_form,
            log_progress=log_progress,
            label=label,
            batch_index=batch_index,
            batch_total=batch_total,
        )
        batch_errors += batch_repair_outcomes.get(
            attachment_service.REPAIR_ERROR, 0
        )

        for form_id, form_sids in sorted(smartva_sids_by_form.items()):
            try:
                va_form = db.session.get(VaForms, form_id)
                if va_form is None:
                    batch_errors += len(form_sids)
                    error_messages.append(
                        f"{form_id}: form-not-found for SmartVA batch {sorted(form_sids)}"
                    )
                    continue

                batch_smartva_generated += int(
                    smartva_service.generate_for_form(
                        va_form,
                        target_sids=form_sids,
                        trigger_source=trigger_source,
                    )
                    or 0
                )
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                batch_errors += len(form_sids)
                error_messages.append(
                    f"{form_id}: SmartVA batch failed for {sorted(form_sids)}: {exc}"
                )

        db.session.rollback()
        run = db.session.execute(
            sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(str(run_id))).with_for_update()
        ).scalar_one_or_none()
        if run is None:
            return totals
        if run.status == "cancelled":
            db.session.commit()
            log_progress(
                f"[{label}] pipeline: parent run already cancelled; "
                f"discarding batch {batch_index}/{batch_total} completion updates."
            )
            return totals

        run.attachment_forms_completed = (run.attachment_forms_completed or 0) + 1
        run.attachment_downloaded = (run.attachment_downloaded or 0) + batch_downloaded
        run.attachment_skipped = (run.attachment_skipped or 0) + batch_skipped
        run.attachment_errors = (run.attachment_errors or 0) + batch_errors
        run.smartva_records_generated = (
            run.smartva_records_generated or 0
        ) + batch_smartva_generated
        for message in error_messages:
            _append_run_error(run, message)
        if finalize_run_on_completion and batch_index >= batch_total:
            run.finished_at = datetime.now(timezone.utc)
            run.status = "partial" if run.error_message or (run.attachment_errors or 0) else "success"
        db.session.commit()

        totals["downloaded"] += batch_downloaded
        totals["non_audit_downloaded"] += batch_non_audit_downloaded
        totals["audit_downloaded"] += batch_audit_downloaded
        totals["smartva_generated"] += batch_smartva_generated
        totals["errors"] += batch_errors
        totals["skipped"] += batch_skipped
        totals["held"] += batch_held

        batch_message = (
            f"[{label}] pipeline: batch {batch_index}/{batch_total} complete — "
            f"{len(batch_sids)} submission(s), "
            f"{batch_downloaded} attachment file(s) downloaded "
            f"(attachments: {batch_non_audit_downloaded}, audit.csv: {batch_audit_downloaded}), "
            f"{batch_smartva_generated} SmartVA result(s) generated"
        )
        if batch_errors:
            batch_message += f", {batch_errors} repair error(s)"
        if batch_held:
            batch_message += f", {batch_held} upstream-changed hold(s)"
        log_progress(batch_message)
        if batch_index < batch_total:
            log_progress(
                f"[{label}] pipeline: batch {batch_index}/{batch_total} complete; "
                f"queueing next batch {batch_index + 1}/{batch_total} "
                f"for {len(batches[batch_index])} submission(s)…"
            )

    if finalize_run_on_completion:
        db.session.rollback()
        run = db.session.execute(
            sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(str(run_id)))
        ).scalar_one_or_none()
        records_added = int((run.records_added if run else 0) or 0)
        records_updated = int((run.records_updated if run else 0) or 0)
        log_progress(
            "Sync finished: "
            f"{records_added} added, {records_updated} updated, "
            f"{totals['downloaded']} attachments downloaded, "
            f"{totals['smartva_generated']} SmartVA result(s) generated."
        )
    return totals


def _prepare_run_for_canonical_repair(run_id, *, candidate_sids: list[str]) -> int:
    """Reserve canonical repair batch slots on a run before async dispatch."""
    from uuid import UUID
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    unique_candidate_sids = list(dict.fromkeys(candidate_sids or []))
    if not unique_candidate_sids:
        return 0
    batch_count = (
        (len(unique_candidate_sids) + ENRICHMENT_SYNC_BATCH_SIZE - 1)
        // ENRICHMENT_SYNC_BATCH_SIZE
    )

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(str(run_id))).with_for_update()
    ).scalar_one_or_none()
    if run is None:
        return 0

    run.attachment_forms_total = (run.attachment_forms_total or 0) + batch_count
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
    return batch_count


def _is_run_cancelled(*, run_id) -> bool:
    """Return True when the parent sync run has already been cancelled."""
    from uuid import UUID
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    status = db.session.scalar(
        sa.select(VaSyncRun.status).where(VaSyncRun.sync_run_id == UUID(str(run_id)))
    )
    return status == "cancelled"


def _finalize_repair_run_if_ready(*, run_id, log_progress) -> bool:
    """Finalize a sync run once all reserved canonical repair batches finish."""
    from uuid import UUID
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(str(run_id))).with_for_update()
    ).scalar_one_or_none()
    if run is None:
        return True
    if run.status == "cancelled":
        db.session.commit()
        return True
    if run.finished_at is not None and run.status in {"success", "partial", "error"}:
        db.session.commit()
        return True

    total = int(run.attachment_forms_total or 0)
    completed = int(run.attachment_forms_completed or 0)
    if completed < total:
        db.session.commit()
        return False

    records_added = int((run.records_added or 0))
    records_updated = int((run.records_updated or 0))
    attachments_downloaded = int((run.attachment_downloaded or 0))
    smartva_generated = int((run.smartva_records_generated or 0))
    run.finished_at = datetime.now(timezone.utc)
    run.status = "partial" if run.error_message or (run.attachment_errors or 0) else "success"
    db.session.commit()
    log_progress(
        "Sync finished: "
        f"{records_added} added, {records_updated} updated, "
        f"{attachments_downloaded} attachments downloaded, "
        f"{smartva_generated} SmartVA result(s) generated."
    )
    return True


def _canonical_repair_tasks_exist_for_run(celery_app, *, run_id: str) -> bool | None:
    """Return whether active/reserved canonical repair tasks still exist for a run.

    Returns None when Celery inspect data is unavailable so callers can retry
    conservatively instead of incorrectly marking a run interrupted.
    """
    inspect = celery_app.control.inspect(timeout=1.0)
    active = inspect.active()
    reserved = inspect.reserved()
    if active is None or reserved is None:
        return None

    def _matches(task: dict) -> bool:
        return (
            task.get("name") == "app.tasks.sync_tasks.run_canonical_repair_batches_task"
            and str((task.get("kwargs") or {}).get("run_id")) == str(run_id)
        )

    for task_list in list(active.values()) + list(reserved.values()):
        for task in task_list or []:
            if _matches(task):
                return True
    return False


def _mark_run_interrupted(*, run_id: str, message: str) -> None:
    """Mark a sync run interrupted/error if it is still open."""
    from uuid import UUID
    from app import db
    from app.models.va_sync_runs import VaSyncRun

    run = db.session.execute(
        sa.select(VaSyncRun).where(VaSyncRun.sync_run_id == UUID(str(run_id))).with_for_update()
    ).scalar_one_or_none()
    if run is None:
        return
    if run.finished_at is not None and run.status in {"success", "partial", "error", "cancelled"}:
        db.session.commit()
        return
    run.status = "error"
    run.finished_at = datetime.now(timezone.utc)
    run.error_message = message
    db.session.commit()


@shared_task(
    name="app.tasks.sync_tasks.run_canonical_repair_batches_task",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_canonical_repair_batches_task(
    self,
    *,
    run_id: str,
    form_id: str,
    candidate_sids: list[str],
    trigger_source: str,
    force_attachment_redownload: bool = False,
):
    """Async wrapper around the canonical per-submission repair engine."""
    from app import db

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    return _run_canonical_repair_batches(
        run_id=run_id,
        label=form_id,
        candidate_sids=candidate_sids,
        trigger_source=trigger_source,
        force_attachment_redownload=force_attachment_redownload,
        log_progress=log_progress,
        finalize_run_on_completion=False,
        count_total_on_entry=False,
    )


@shared_task(
    name="app.tasks.sync_tasks.finalize_canonical_repair_run_task",
    bind=True,
    soft_time_limit=300,
    time_limit=600,
    max_retries=None,
)
def finalize_canonical_repair_run_task(
    self,
    *,
    run_id: str,
    label: str,
):
    """Finalize a run after all reserved canonical repair batches complete."""
    from app import db

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    if _finalize_repair_run_if_ready(run_id=run_id, log_progress=log_progress):
        return {"finalized": True}
    pending_repair_tasks = _canonical_repair_tasks_exist_for_run(self.app, run_id=run_id)
    if pending_repair_tasks is False:
        _mark_run_interrupted(
            run_id=run_id,
            message=INTERRUPTED_RUN_MESSAGE,
        )
        log_progress(INTERRUPTED_RUN_MESSAGE)
        return {"finalized": False, "interrupted": True}
    raise self.retry(countdown=10)


def _build_repair_map_for_form(
    form_id: str,
    raw_submissions: list[dict],
    upserted_map: dict[str, str],
    *,
    target_sids: list[str] | None = None,
) -> tuple[dict[str, dict], dict[str, int]]:
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

    if raw_by_sid:
        scoped_target_sids = list(raw_by_sid.keys())
    else:
        scoped_target_sids = target_sids
    attachment_states = attachment_state_by_submission(
        form_id,
        target_sids=scoped_target_sids,
    )
    legacy_attachment_rows = _legacy_attachment_rows_by_submission(
        form_id,
        target_sids=scoped_target_sids,
    )

    stmt = (
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
        .where(VaSubmissions.va_form_id == form_id)
    )
    if scoped_target_sids:
        stmt = stmt.where(VaSubmissions.va_sid.in_(scoped_target_sids))

    rows = db.session.execute(stmt).all()

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
        "legacy_attachment_rows": 0,
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
        legacy_attachment_count = int(legacy_attachment_rows.get(va_sid) or 0)
        # Completeness is readiness, not a file count: a row counts only when
        # its blob is in DigitVA's store and, for audio, its MP3 derivative is
        # ready. A submission retired from ODK is complete by policy — its
        # source is gone and no repair may ever run
        # (docs/policy/odk-retired-submissions.md).
        attachment_state = attachment_states.get(va_sid)
        if attachment_state is not None and attachment_state.retired:
            attachments_complete = True
        else:
            ready_attachment_count = (
                attachment_state.ready_count if attachment_state else 0
            )
            unready_attachments = (
                attachment_state.unready if attachment_state else ()
            )
            attachments_complete = (
                ready_attachment_count >= attachments_expected
                and not unready_attachments
                and legacy_attachment_count == 0
            )
        summary["legacy_attachment_rows"] += legacy_attachment_count
        smartva_complete = smartva_present_sid is not None
        if not metadata_complete:
            summary["metadata_missing"] += 1
        if not attachments_complete:
            summary["attachments_missing"] += 1
        if not smartva_complete:
            summary["smartva_missing"] += 1
        if not metadata_complete or not attachments_complete or not smartva_complete:
            existing = repair_map.get(
                va_sid,
                {
                    "instance_id": instance_id,
                    "needs_metadata": False,
                    "needs_attachments": False,
                    "needs_smartva": False,
                    "legacy_attachment_rows": 0,
                },
            )
            existing["instance_id"] = existing.get("instance_id") or instance_id
            existing["needs_metadata"] = bool(existing.get("needs_metadata")) or (not metadata_complete)
            existing["needs_attachments"] = bool(existing.get("needs_attachments")) or (not attachments_complete)
            existing["needs_smartva"] = bool(existing.get("needs_smartva")) or (not smartva_complete)
            existing["legacy_attachment_rows"] = max(
                int(existing.get("legacy_attachment_rows") or 0),
                legacy_attachment_count,
            )
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
            candidate_sids = list(upserted_map.keys())
            if not candidate_sids:
                return
            _prepare_run_for_canonical_repair(run_id, candidate_sids=candidate_sids)
            progress_callback(
                f"[{va_form.form_id}] repair: queueing {len(candidate_sids)} "
                "changed submission(s) through the canonical repair engine…"
            )
            run_canonical_repair_batches_task.delay(
                run_id=str(run_id),
                form_id=va_form.form_id,
                candidate_sids=candidate_sids,
                trigger_source="odk_sync",
                force_attachment_redownload=False,
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
            db.session.commit()
            finalize_canonical_repair_run_task.delay(
                run_id=str(run_id),
                label="Sync",
            )
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
                f"legacy attachment records pending migration: {repair_summary['legacy_attachment_rows']}, "
                f"SmartVA gaps: {repair_summary['smartva_missing']})…"
            )
            _prepare_run_for_canonical_repair(run_id, candidate_sids=list(repair_map.keys()))
            run_canonical_repair_batches_task.delay(
                run_id=str(run_id),
                form_id=form_id,
                candidate_sids=list(repair_map.keys()),
                trigger_source="single_form_sync",
                force_attachment_redownload=False,
            )
            finalize_canonical_repair_run_task.delay(
                run_id=str(run_id),
                label=form_id,
            )

        # Update last_synced_at
        from app.services.runtime_form_sync_service import get_active_mapping_for_form

        mapping = get_active_mapping_for_form(va_form)
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
    soft_time_limit=1800,
    time_limit=3600,
)
def run_single_form_backfill(self, form_id: str, triggered_by: str = "backfill", user_id=None):
    """Repair local gaps for one form without doing a full force-resync."""
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
        repair_dispatched = False
        dispatched_candidate_count = 0

        existing_repair_map, existing_repair_summary = _build_repair_map_for_form(
            form_id,
            [],
            {},
            target_sids=sorted(local_sids),
        )
        if existing_repair_map:
            repair_dispatched = True
            dispatched_candidate_count += len(existing_repair_map)
            log_progress(
                f"[{form_id}] Backfill: queueing {len(existing_repair_map)} existing local submission(s) "
                f"for repair (metadata gaps: {existing_repair_summary['metadata_missing']}, "
                f"missing local attachment files: {existing_repair_summary['attachments_missing']}, "
                f"legacy attachment records pending migration: {existing_repair_summary['legacy_attachment_rows']}, "
                f"SmartVA gaps: {existing_repair_summary['smartva_missing']})"
            )
            _prepare_run_for_canonical_repair(
                run_id,
                candidate_sids=list(existing_repair_map.keys()),
            )
            run_canonical_repair_batches_task.delay(
                run_id=str(run_id),
                form_id=form_id,
                candidate_sids=list(existing_repair_map.keys()),
                trigger_source="backfill",
                force_attachment_redownload=False,
            )

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
            added += b_added
            updated += b_updated
            discarded += b_discarded
            skipped += b_skipped
            done = min(batch_start + gap_batch_size, len(missing_ids))
            log_progress(
                f"[{form_id}] backfill data: fetched {done}/{len(missing_ids)} missing submission(s)"
            )

            batch_repair_map, batch_repair_summary = _build_repair_map_for_form(
                form_id,
                batch_records,
                batch_upserted_map,
                target_sids=list(batch_upserted_map.keys()),
            )
            if batch_repair_map:
                repair_dispatched = True
                dispatched_candidate_count += len(batch_repair_map)
                log_progress(
                    f"[{form_id}] Backfill: queueing {len(batch_repair_map)} fetched submission(s) "
                    f"for immediate repair (metadata gaps: {batch_repair_summary['metadata_missing']}, "
                    f"missing local attachment files: {batch_repair_summary['attachments_missing']}, "
                    f"legacy attachment records pending migration: {batch_repair_summary['legacy_attachment_rows']}, "
                    f"SmartVA gaps: {batch_repair_summary['smartva_missing']})"
                )
                _prepare_run_for_canonical_repair(
                    run_id,
                    candidate_sids=list(batch_repair_map.keys()),
                )
                run_canonical_repair_batches_task.delay(
                    run_id=str(run_id),
                    form_id=form_id,
                    candidate_sids=list(batch_repair_map.keys()),
                    trigger_source="backfill",
                    force_attachment_redownload=False,
                )

        run = db.session.get(VaSyncRun, run_id)
        run.records_added = added
        run.records_updated = updated
        run.smartva_records_generated = 0

        if repair_dispatched:
            run.status = "running"
            db.session.commit()
            finalize_canonical_repair_run_task.delay(
                run_id=str(run_id),
                label=form_id,
            )
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
            dispatched_candidate_count if repair_dispatched else 0,
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


# One admin repair action never sweeps a whole form in a single run; the panel
# button is meant to be pressed again.
ATTACHMENT_PANEL_REPAIR_MAX_SUBMISSIONS = 200


@shared_task(
    name="app.tasks.sync_tasks.run_form_attachment_repair",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_form_attachment_repair(self, *, run_id: str, form_id: str):
    """Repair one form's unready attachments through the canonical repair engine.

    Candidates come from ``attachment_service.attachment_state_by_submission()``
    — submissions whose attachments are not ready and which are not retired —
    and are capped at ``ATTACHMENT_PANEL_REPAIR_MAX_SUBMISSIONS`` so one press
    of the admin button can never become an unbounded run. The run row is
    created by the caller so it can hand the operator its id immediately.
    """
    from uuid import UUID

    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services import attachment_service

    def log_progress(msg):
        _log_progress(db, run_id, msg)

    try:
        states = attachment_service.attachment_state_by_submission(form_id)
        candidate_sids = sorted(
            va_sid
            for va_sid, state in states.items()
            if state.unready and not state.retired
        )[:ATTACHMENT_PANEL_REPAIR_MAX_SUBMISSIONS]
        if not candidate_sids:
            run = db.session.get(VaSyncRun, UUID(str(run_id)))
            if run:
                run.status = "success"
                run.finished_at = datetime.now(timezone.utc)
                db.session.commit()
            log_progress(f"[{form_id}] attachment repair: nothing to repair")
            return {"repaired_submissions": 0}

        log_progress(
            f"[{form_id}] attachment repair: queueing "
            f"{len(candidate_sids)} submission(s)"
        )
        return _run_canonical_repair_batches(
            run_id=run_id,
            label=form_id,
            candidate_sids=candidate_sids,
            trigger_source="attachment_panel_repair",
            force_attachment_redownload=False,
            log_progress=log_progress,
        )
    except SoftTimeLimitExceeded:
        db.session.rollback()
        run = db.session.get(VaSyncRun, UUID(str(run_id)))
        if run:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = INTERRUPTED_RUN_MESSAGE
            db.session.commit()
        raise
    except Exception as exc:
        db.session.rollback()
        log.error("Attachment repair failed for %s", form_id, exc_info=True)
        run = db.session.get(VaSyncRun, UUID(str(run_id)))
        if run:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(exc)[:2000]
            db.session.commit()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_attachment_integrity_check",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_attachment_integrity_check(
    self,
    form_id: str | None = None,
    triggered_by: str = "att-integrity",
    user_id=None,
):
    """Compare attachment rows against the store and record counts on a run row.

    The work is ``attachment_service.integrity_check_summary()``; this task only
    gives an operator somewhere to watch it from. Read-only against both the DB
    and the store, and the progress log holds counts only — never a path, a key,
    or a submission identifier.
    """
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services import attachment_service

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
        log_progress(
            f"attachment integrity: started (scope {form_id or 'ALL'})"
        )
        summary = attachment_service.integrity_check_summary(form_id=form_id)
        log_progress(
            "attachment integrity: "
            + ", ".join(f"{key}={value}" for key, value in sorted(summary.items()))
        )
        run = db.session.get(VaSyncRun, run_id)
        run.status = "success" if summary.get("clean") else "partial"
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        return summary
    except SoftTimeLimitExceeded:
        db.session.rollback()
        run = db.session.get(VaSyncRun, run_id)
        if run:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = INTERRUPTED_RUN_MESSAGE
            db.session.commit()
        raise
    except Exception as exc:
        db.session.rollback()
        log.error("Attachment integrity check failed", exc_info=True)
        run = db.session.get(VaSyncRun, run_id)
        if run:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(exc)[:2000]
            db.session.commit()
        raise


def _lock_client():
    """The Redis client behind Flask-Caching, or ``None`` when there is none."""
    from app import cache

    try:
        return cache.cache._write_client  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a missing lock must not stop the work
        return None


@contextmanager
def _sweep_lock(key: str, ttl_seconds: int):
    """Hold ``key`` for the block, or yield ``False`` if someone else holds it.

    A cross-worker mutex over the Redis the app already has, not a correctness
    guarantee: every step of a sweep is idempotent, so a sweep that cannot
    reach Redis runs anyway rather than letting the backlog grow. The value is
    a token and release deletes the key only while it is still ours, so a lock
    that expired and was taken over by the next sweep is never released by
    this one.
    """
    client = _lock_client()
    if client is None:
        yield True
        return

    token = uuid.uuid4().hex
    try:
        acquired = bool(client.set(key, token, nx=True, ex=ttl_seconds))
    except Exception:  # noqa: BLE001 - an unreachable lock must not stop the work
        log.warning("lock %s is unavailable; running without it", key, exc_info=True)
        yield True
        return

    if not acquired:
        yield False
        return
    try:
        yield True
    finally:
        try:
            current = client.get(key)
            if current in (token, token.encode()):
                client.delete(key)
        except Exception:  # noqa: BLE001 - the TTL releases it either way
            log.warning("lock %s could not be released; it expires", key, exc_info=True)


def _finish_sweep_run(run, *, status, uploaded=0, remaining=0, error=None):
    """Close an attachment sweep's run row with its counts. No-op without one."""
    from app import db

    if run is None:
        return
    run.status = status
    run.records_updated = uploaded
    run.records_skipped = remaining
    run.finished_at = datetime.now(timezone.utc)
    if error:
        run.error_message = error[:2000]
    db.session.commit()


@shared_task(
    name="app.tasks.sync_tasks.run_attachment_s3_upload",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_attachment_s3_upload(
    self,
    form_id: str | None = None,
    limit: int = ATTACHMENT_S3_UPLOAD_TASK_LIMIT,
    triggered_by: str = S3_UPLOAD_TRIGGER,
    user_id=None,
    run_id=None,
):
    """Copy up to ``limit`` attachment blobs into the bucket and verify them.

    The work is ``attachment_service.s3_upload_backlog()``; this task only
    gives beat and the admin panel somewhere to call it from. It is the
    cutover mechanism *and* the standing self-heal: any row that later ends up
    with ``store_state='local'`` is picked up by the next sweep.

    Two no-ops cost one query and write nothing: the local store, and an empty
    backlog. A *scheduled* sweep in either state records no run row at all —
    the sweep fires every few minutes, and 150 empty rows a day would bury the
    real sync history the dashboard exists to show. A sweep started from the
    panel passes its own ``run_id``, so an operator who pressed the button
    always gets a row back, marked ``success`` with ``remaining=0``.

    Never raises: a failed upload is counted on the run row, and a traceback
    into beat would only repeat the same failure in a few minutes. The
    progress log holds counts only — never a path, a key, or a submission id.
    """
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services import attachment_service
    from app.services.attachment_service import STORE_STATE_S3
    from app.services.attachment_store import get_attachment_store

    run = db.session.get(VaSyncRun, uuid.UUID(str(run_id))) if run_id else None
    batch = max(int(limit or 0), 0) or ATTACHMENT_S3_UPLOAD_TASK_LIMIT

    if get_attachment_store().name != STORE_STATE_S3:
        log.info("attachment s3 upload: ATTACHMENT_STORE is not 's3'; nothing to do")
        _finish_sweep_run(run, status="success")
        return {"skipped": "local_store", "scanned": 0, "uploaded": 0,
                "failed": 0, "remaining": 0}

    remaining = attachment_service.s3_upload_pending_count(form_id=form_id)
    if not remaining:
        log.info("attachment s3 upload: backlog empty (scope %s)", form_id or "ALL")
        _finish_sweep_run(run, status="success")
        return {"skipped": "empty_backlog", "scanned": 0, "uploaded": 0,
                "failed": 0, "remaining": 0}

    with _sweep_lock(
        ATTACHMENT_S3_UPLOAD_LOCK_KEY, ATTACHMENT_S3_UPLOAD_LOCK_TTL_SECONDS
    ) as acquired:
        if not acquired:
            log.info("attachment s3 upload: another sweep is running; skipping")
            _finish_sweep_run(run, status="success", remaining=remaining)
            return {"skipped": "locked", "scanned": 0, "uploaded": 0,
                    "failed": 0, "remaining": remaining}

        if run is None:
            run = VaSyncRun(
                triggered_by=triggered_by,
                triggered_user_id=user_id,
                started_at=datetime.now(timezone.utc),
                status="running",
            )
            db.session.add(run)
            db.session.commit()
        sweep_run_id = run.sync_run_id

        def log_progress(msg):
            _log_progress(db, sweep_run_id, msg)

        log_progress(
            f"attachment s3 upload: started (scope {form_id or 'ALL'}, "
            f"limit {batch}, awaiting {remaining})"
        )
        try:
            counts = attachment_service.s3_upload_backlog(
                form_id=form_id,
                limit=batch,
                on_progress=log_progress,
            )
        except SoftTimeLimitExceeded:
            db.session.rollback()
            log_progress("attachment s3 upload: interrupted")
            _finish_sweep_run(
                run, status="error", remaining=remaining,
                error=INTERRUPTED_RUN_MESSAGE,
            )
            return {"skipped": "interrupted", "scanned": 0, "uploaded": 0,
                    "failed": 0, "remaining": remaining}
        except Exception as exc:  # noqa: BLE001 - a sweep must not crash beat
            db.session.rollback()
            log.error("Attachment S3 upload sweep failed", exc_info=True)
            log_progress("attachment s3 upload: failed")
            _finish_sweep_run(
                run, status="error", remaining=remaining, error=str(exc),
            )
            return {"skipped": "error", "scanned": 0, "uploaded": 0,
                    "failed": 0, "remaining": remaining}

        remaining = attachment_service.s3_upload_pending_count(form_id=form_id)
        result = {
            "scanned": counts["scanned"],
            "uploaded": counts["uploaded"],
            "failed": counts["failed"],
            "remaining": remaining,
        }
        log_progress(
            "attachment s3 upload: "
            + " ".join(f"{key}={value}" for key, value in result.items())
        )
        # counts["failures"] names the form and the storage name of each
        # failure; the progress log never carries either, so only the count
        # travels. The operator's detail view is `flask attachments s3-upload`.
        _finish_sweep_run(
            run,
            status="success" if not counts["failed"] else "partial",
            uploaded=counts["uploaded"],
            remaining=remaining,
            error=(
                f"{counts['failed']} attachment(s) could not be uploaded."
                if counts["failed"] else None
            ),
        )
        return result


@shared_task(
    name="app.tasks.sync_tasks.run_attachment_local_quarantine",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_attachment_local_quarantine(
    self,
    form_id: str | None = None,
    include_retained: bool = False,
    triggered_by: str = QUARANTINE_TRIGGER,
    user_id=None,
):
    """Move the local copies of verified S3-stored rows aside. Manual only.

    The work is ``attachment_service.quarantine_local_copies()``. Nothing is
    deleted: a file moves only once its object is confirmed in the bucket, and
    removing the quarantine after the retention window stays a manual,
    documented step — which is exactly why this task is never scheduled. A
    no-op on the local store. Never raises; counts only in the progress log.
    """
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services import attachment_service
    from app.services.attachment_service import STORE_STATE_S3
    from app.services.attachment_store import get_attachment_store

    if get_attachment_store().name != STORE_STATE_S3:
        log.info("attachment quarantine: ATTACHMENT_STORE is not 's3'; nothing to do")
        return {"skipped": "local_store", "moved": 0}

    run = VaSyncRun(
        triggered_by=triggered_by,
        triggered_user_id=user_id,
        started_at=datetime.now(timezone.utc),
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    sweep_run_id = run.sync_run_id

    def log_progress(msg):
        _log_progress(db, sweep_run_id, msg)

    log_progress(f"attachment quarantine: started (scope {form_id or 'ALL'})")
    try:
        counts = attachment_service.quarantine_local_copies(
            form_id=form_id,
            include_retained=bool(include_retained),
        )
    except Exception as exc:  # noqa: BLE001 - an operator sees the run row
        db.session.rollback()
        log.error("Attachment local quarantine failed", exc_info=True)
        log_progress("attachment quarantine: failed")
        _finish_sweep_run(run, status="error", error=str(exc))
        return {"skipped": "error", "moved": 0}

    log_progress(
        "attachment quarantine: "
        + " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
    _finish_sweep_run(
        run,
        status="success" if not counts["skipped_no_object"] else "partial",
        uploaded=counts["moved"],
    )
    return counts


@shared_task(
    name="app.tasks.sync_tasks.run_smartva_run_archive",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_smartva_run_archive(
    self,
    form_id: str | None = None,
    limit: int = SMARTVA_ARCHIVE_TASK_LIMIT,
    delete_local: bool = True,
    triggered_by: str = "smartva-archive",
    user_id=None,
):
    """Archive SmartVA run directories to the object store and free the VM.

    The work is ``smartva_run_archive_service.archive_run_backlog()``; this task
    only gives an operator somewhere to watch it from. Bounded per press — one
    run of this task never sweeps more than ``limit`` run directories, so a
    backlog is cleared by repeated presses rather than one unbounded job. On the
    local store it does nothing. The progress log holds counts and failure
    categories only — never a path, a key, or a submission identifier.
    """
    from app import db
    from app.models.va_sync_runs import VaSyncRun
    from app.services import smartva_run_archive_service

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
        log_progress(f"smartva run archive: started (scope {form_id or 'ALL'})")
        counts = smartva_run_archive_service.archive_run_backlog(
            form_id=form_id,
            limit=max(int(limit or 0), 0) or SMARTVA_ARCHIVE_TASK_LIMIT,
            delete_local=bool(delete_local),
            on_progress=log_progress,
        )
        log_progress(
            "smartva run archive: "
            + ", ".join(
                f"{key}={value}"
                for key, value in sorted(counts.items())
                if key != "failures"
            )
        )
        for failure in counts["failures"][:20]:
            log_progress(f"smartva run archive failure: {failure}")
        run = db.session.get(VaSyncRun, run_id)
        run.records_updated = counts["archived"]
        run.status = "success" if not counts["failed"] else "partial"
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        return counts
    except SoftTimeLimitExceeded:
        db.session.rollback()
        run = db.session.get(VaSyncRun, run_id)
        if run:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = INTERRUPTED_RUN_MESSAGE
            db.session.commit()
        raise
    except Exception as exc:
        db.session.rollback()
        log.error("SmartVA run archive failed", exc_info=True)
        run = db.session.get(VaSyncRun, run_id)
        if run:
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(exc)[:2000]
            db.session.commit()
        raise


@shared_task(
    name="app.tasks.sync_tasks.run_legacy_attachment_repair",
    bind=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_legacy_attachment_repair(
    self,
    triggered_by: str = "legacy-repair",
    user_id=None,
):
    """Repair legacy attachment rows through the canonical repair engine."""
    from app import db
    from app.models import VaSubmissionAttachments
    from app.models.va_sync_runs import VaSyncRun

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
        legacy_sids = list(
            dict.fromkeys(
                db.session.scalars(
                    sa.select(VaSubmissionAttachments.va_sid).where(
                        VaSubmissionAttachments.exists_on_odk.is_(True),
                        VaSubmissionAttachments.storage_name.is_(None),
                    )
                ).all()
            )
        )
        run = db.session.get(VaSyncRun, run_id)
        db.session.commit()
        if not legacy_sids:
            run = db.session.get(VaSyncRun, run_id)
            run.records_updated = 0
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
            log_progress("legacy-attachment repair: no legacy attachment rows found")
        else:
            log_progress(
                "legacy-attachment repair: queueing "
                f"{len(legacy_sids)} submission(s) with legacy rows"
            )
            totals = _run_canonical_repair_batches(
                run_id=run_id,
                label="legacy-attachment-repair",
                candidate_sids=legacy_sids,
                trigger_source="legacy_attachment_repair",
                force_attachment_redownload=False,
                log_progress=log_progress,
            )
            run = db.session.get(VaSyncRun, run_id)
            run.records_updated = int(totals.get("downloaded") or 0)
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
                f"[{va_form.form_id}] repair: queueing {len(upserted_map)} changed "
                f"submission(s) through the canonical repair engine…"
            )
            _prepare_run_for_canonical_repair(run_id, candidate_sids=list(upserted_map.keys()))
            run_canonical_repair_batches_task.delay(
                run_id=str(run_id),
                form_id=va_form.form_id,
                candidate_sids=list(upserted_map.keys()),
                trigger_source="single_submission_sync",
                force_attachment_redownload=False,
            )
            finalize_canonical_repair_run_task.delay(
                run_id=str(run_id),
                label=va_form.form_id,
            )
        _mark_form_sync_issues(va_form, va_odk_fetch_instance_ids(va_form, client=odk_client))
        db.session.commit()

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
    name="app.tasks.sync_tasks.run_open_submission_repair",
    bind=True,
    soft_time_limit=600,
    time_limit=900,
)
def run_open_submission_repair(
    self,
    *,
    va_sid: str,
    trigger_source: str = "open_view_repair",
):
    """Run the canonical current-payload repair engine asynchronously for one submission."""
    from app import db
    from app.services.open_submission_repair_service import repair_submission_current_payload

    try:
        result = repair_submission_current_payload(
            va_sid,
            trigger_source=trigger_source,
        )
        log.info(
            "OpenSubmissionRepairTask [%s]: attempted=%s attachments=%s smartva=%s source=%s",
            va_sid,
            result.get("attempted"),
            result.get("attachments_downloaded", 0),
            result.get("smartva_generated", 0),
            trigger_source,
        )
        return result
    except Exception as exc:
        db.session.rollback()
        log.error(
            "OpenSubmissionRepairTask [%s]: failed — %s",
            va_sid,
            exc,
            exc_info=True,
        )
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
                error_message = :msg
            WHERE status = 'running'
              AND started_at < NOW() - INTERVAL '45 minutes'
        """), {"msg": INTERRUPTED_RUN_MESSAGE})
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


def parse_sweep_minutes(value) -> int:
    """``ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES`` as a positive int, or the default.

    A missing, unparseable or non-positive value is a misconfiguration, not a
    reason to stop sweeping the upload backlog, so it is logged and the default
    is used. Capped at a day: an interval longer than that is a typo, and the
    sweep is also the standing self-heal for a row that drops back to local.
    """
    try:
        minutes = int(value)
        if not (1 <= minutes <= 1440):
            raise ValueError(value)
    except (TypeError, ValueError):
        log.warning(
            "ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES is not a minute count between "
            "1 and 1440; using %s",
            DEFAULT_ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES,
        )
        minutes = DEFAULT_ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES
    return minutes


def ensure_attachment_s3_upload_scheduled():
    """Seed the attachment S3 upload sweep beat entry. Idempotent.

    Left scheduled permanently, on every deployment: the task costs one count
    query when the store is local or the backlog is empty, and keeping it on
    means a row that somehow returns to ``store_state='local'`` is copied back
    into the bucket without anyone noticing it had to be. The interval is
    configuration, so a changed ``ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES`` repoints
    the existing row rather than adding a second one.
    """
    try:
        from flask import current_app

        from app import db

        minutes = parse_sweep_minutes(
            current_app.config.get("ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES")
        )

        with db.engine.begin() as conn:
            schedule_id = conn.execute(
                sa.text(
                    "SELECT id FROM public.celery_intervalschedule "
                    "WHERE every = :every AND period = 'minutes' LIMIT 1"
                ),
                {"every": minutes},
            ).scalar()
            if schedule_id is None:
                schedule_id = conn.execute(
                    sa.text(
                        "INSERT INTO public.celery_intervalschedule (every, period) "
                        "VALUES (:every, 'minutes') RETURNING id"
                    ),
                    {"every": minutes},
                ).scalar()

            existing_schedule_id = conn.execute(
                sa.text(
                    "SELECT schedule_id FROM public.celery_periodictask "
                    "WHERE name = :name LIMIT 1"
                ),
                {"name": ATTACHMENT_S3_UPLOAD_SCHEDULE_NAME},
            ).scalar()

            if existing_schedule_id is None:
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
                        "name": ATTACHMENT_S3_UPLOAD_SCHEDULE_NAME,
                        "task": "app.tasks.sync_tasks.run_attachment_s3_upload",
                        "schedule_id": schedule_id,
                    },
                )
            elif existing_schedule_id != schedule_id:
                conn.execute(
                    sa.text(
                        "UPDATE public.celery_periodictask SET schedule_id = :schedule_id, "
                        "discriminator = 'intervalschedule' WHERE name = :name"
                    ),
                    {"schedule_id": schedule_id,
                     "name": ATTACHMENT_S3_UPLOAD_SCHEDULE_NAME},
                )
            else:
                return

            conn.execute(
                sa.text(
                    "INSERT INTO public.celery_periodictaskchanged (last_update) "
                    "VALUES (NOW()) ON CONFLICT DO NOTHING"
                )
            )

        log.info(
            "Attachment S3 upload sweep beat schedule seeded: every %d minute(s).",
            minutes,
        )
    except Exception as e:
        log.warning("Could not seed attachment S3 upload schedule: %s", e)
