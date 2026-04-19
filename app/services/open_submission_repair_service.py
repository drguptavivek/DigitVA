"""Canonical per-submission current-payload repair engine.

This module holds the shared repair implementation for one submission's current
payload. Different entrypoints may choose candidates differently, but they
should converge on this repair engine instead of re-implementing attachment or
SmartVA repair logic separately.
"""

from __future__ import annotations

import logging
import os

import sqlalchemy as sa

from app import db
from app.models import VaForms, VaSubmissions
from app.services import smartva_service
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    _attach_all_odk_comments,
    _finalize_enriched_submissions_for_form,
)
from app.services.workflow.definition import (
    WORKFLOW_ATTACHMENT_SYNC_PENDING,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    mark_attachment_sync_completed,
    mark_smartva_completed,
    system_actor,
)
from app.tasks.sync_tasks import (
    _build_repair_map_for_form,
    _get_single_form_odk_client,
    _normalize_batch_plan,
    _refresh_batch_plan_after_enrichment,
    _release_read_transaction,
)
from app.utils import va_odk_fetch_submissions_by_ids, va_odk_sync_form_attachments

log = logging.getLogger(__name__)


def _load_payload_rows(va_sid: str) -> list[tuple[str, dict]]:
    from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion

    rows = db.session.execute(
        sa.select(VaSubmissions.va_sid, VaSubmissionPayloadVersion.payload_data)
        .outerjoin(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .where(VaSubmissions.va_sid == va_sid)
    ).all()
    return [(sid, payload_data or {}) for sid, payload_data in rows]


def _advance_workflow_after_current_payload_repair(
    *,
    va_sid: str,
    needs_attachments: bool,
    needs_smartva: bool,
) -> None:
    """Advance workflow when canonical repair has satisfied current-payload gaps."""
    current_state = get_submission_workflow_state(va_sid)
    if current_state == WORKFLOW_ATTACHMENT_SYNC_PENDING and not needs_attachments:
        mark_attachment_sync_completed(
            va_sid,
            reason="attachments_synced_for_current_payload",
            actor=system_actor(),
        )
        current_state = get_submission_workflow_state(va_sid)

    if current_state == WORKFLOW_SMARTVA_PENDING and not needs_smartva:
        mark_smartva_completed(
            va_sid,
            reason="smartva_completed_for_current_payload",
            actor=system_actor(),
        )


def repair_submission_current_payload(
    va_sid: str,
    *,
    trigger_source: str = "single_submission_repair",
    force_attachment_redownload: bool = False,
    run_smartva: bool = True,
) -> dict:
    """Repair the current payload for one submission synchronously.

    This is the canonical repair engine for per-submission current-payload
    repair. Callers should prefer reusing this function rather than duplicating
    payload revalidation, attachment repair, and SmartVA follow-through.
    """
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        return {"attempted": False, "reason": "submission-not-found"}

    va_form = db.session.get(VaForms, submission.va_form_id)
    if va_form is None:
        return {"attempted": False, "reason": "form-not-found"}

    repair_map, summary = _build_repair_map_for_form(
        va_form.form_id,
        [],
        {},
        target_sids=[va_sid],
    )
    plan_item = repair_map.get(va_sid)
    if plan_item is None:
        return {
            "attempted": False,
            "reason": "no-gaps",
            "summary": summary,
        }

    batch_plan = _normalize_batch_plan({va_sid: plan_item})
    payload_rows = _load_payload_rows(va_sid)
    payload_by_sid = {sid: dict(payload_data or {}) for sid, payload_data in payload_rows}
    if not batch_plan[va_sid].get("instance_id"):
        batch_plan[va_sid]["instance_id"] = payload_by_sid.get(va_sid, {}).get("KEY", "")

    result = {
        "attempted": True,
        "metadata_enriched": 0,
        "attachments_downloaded": 0,
        "non_audit_downloaded": 0,
        "audit_downloaded": 0,
        "smartva_generated": 0,
        "needs_smartva_after_repair": False,
        "upstream_changed_held": False,
        "initial_summary": summary,
        "form_id": va_form.form_id,
    }

    upserted_map = {
        va_sid: batch_plan[va_sid].get("instance_id") or ""
    } if batch_plan[va_sid].get("instance_id") else {}
    revalidation_ids = list(dict.fromkeys(upserted_map.values()))
    raw_submissions: list[dict] = []
    amended_sids: set[str] = set()

    try:
        _release_read_transaction(va_form)
        odk_client = _get_single_form_odk_client(va_form)

        fetched_submissions = (
            va_odk_fetch_submissions_by_ids(
                va_form,
                revalidation_ids,
                client=odk_client,
            )
            if revalidation_ids
            else []
        )
        fetched_submissions = _attach_all_odk_comments(
            va_form,
            fetched_submissions,
            client=odk_client,
        )
        raw_by_sid = {
            submission.get("sid"): submission
            for submission in fetched_submissions
            if submission.get("sid")
        }
        payload = raw_by_sid.get(va_sid) or payload_by_sid.get(va_sid) or {}
        if payload:
            raw_submissions.append(dict(payload))

        enriched_count = _finalize_enriched_submissions_for_form(
            va_form,
            raw_submissions,
            upserted_map,
            amended_sids,
            client=odk_client,
        )
        db.session.commit()
        result["metadata_enriched"] = enriched_count

        batch_plan, refreshed_summary, upstream_changed_count = _refresh_batch_plan_after_enrichment(
            form_id=va_form.form_id,
            batch_plan=batch_plan,
            raw_submissions=raw_submissions,
            upserted_map=upserted_map,
        )
        result["post_enrichment_summary"] = refreshed_summary
        result["upstream_changed_held"] = upstream_changed_count > 0
        if result["upstream_changed_held"]:
            return result

        if batch_plan[va_sid].get("needs_attachments"):
            from flask import current_app

            media_dir = os.path.join(current_app.config["APP_DATA"], va_form.form_id, "media")
            os.makedirs(media_dir, exist_ok=True)
            totals = va_odk_sync_form_attachments(
                va_form,
                {va_sid: batch_plan[va_sid].get("instance_id") or ""},
                media_dir,
                client_factory=lambda: _get_single_form_odk_client(va_form),
                force_redownload=force_attachment_redownload,
            )
            db.session.commit()
            result["attachments_downloaded"] = int(totals.get("downloaded", 0) or 0)
            result["non_audit_downloaded"] = int(totals.get("non_audit_downloaded", 0) or 0)
            result["audit_downloaded"] = int(totals.get("audit_downloaded", 0) or 0)

            batch_plan, refreshed_summary, upstream_changed_count = _refresh_batch_plan_after_enrichment(
                form_id=va_form.form_id,
                batch_plan=batch_plan,
                raw_submissions=raw_submissions,
                upserted_map=upserted_map,
            )
            result["post_attachment_summary"] = refreshed_summary
            result["upstream_changed_held"] = upstream_changed_count > 0
            if result["upstream_changed_held"]:
                return result

        _advance_workflow_after_current_payload_repair(
            va_sid=va_sid,
            needs_attachments=bool(batch_plan[va_sid].get("needs_attachments")),
            needs_smartva=bool(batch_plan[va_sid].get("needs_smartva")),
        )
        db.session.commit()

        result["needs_smartva_after_repair"] = bool(batch_plan[va_sid].get("needs_smartva"))
        if run_smartva and result["needs_smartva_after_repair"]:
            result["smartva_generated"] = smartva_service.generate_for_submission(
                va_sid,
                trigger_source=trigger_source,
            )
            db.session.commit()

        return result
    except Exception:
        db.session.rollback()
        log.warning(
            "OpenSubmissionRepair [%s]: failed",
            va_sid,
            exc_info=True,
        )
        raise


def repair_submission_for_coding_open(va_sid: str) -> dict:
    """Coding-route wrapper around the canonical per-submission repair engine."""
    return repair_submission_current_payload(
        va_sid,
        trigger_source="coding_open_repair",
    )
