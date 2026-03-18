"""Data management API — /api/v1/data-management/

Resources:
  POST forms/<form_id>/sync        — trigger form sync from ODK
  POST sync/preview                — preview what will sync
  GET  sync/runs                   — recent sync run history
  GET  project-site-submissions    — submission stats per project/site
  POST submissions/<sid>/sync      — trigger individual submission refresh
"""

from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace

import sqlalchemy as sa
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

from app import db
from app.models import VaForms, VaSyncRun, VaSubmissions
from app.services.data_management_service import (
    audit_dm_submission_action,
    dm_form_in_scope,
    dm_project_site_submission_stats,
    dm_scoped_forms,
    filter_scoped_forms,
    sync_run_entries,
    sync_run_target_label,
)

bp = Blueprint("data_management_api", __name__)
log = logging.getLogger(__name__)


def _require_data_manager():
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403
    return None


@bp.post("/forms/<form_id>/sync")
@login_required
def sync_form(form_id: str):
    err = _require_data_manager()
    if err:
        return err
    if not dm_form_in_scope(current_user, form_id):
        return jsonify({"error": "You do not have access to sync this form."}), 403

    try:
        from app.tasks.sync_tasks import run_single_form_sync

        if current_app.extensions.get("celery") is None:
            return jsonify({"error": "Celery is not configured."}), 503

        task = run_single_form_sync.delay(
            form_id=form_id,
            triggered_by="data-manager",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": f"Sync started for form {form_id}.", "task_id": task.id}), 202
    except Exception as exc:
        log.error("sync_form failed for %s", form_id, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@bp.post("/sync/preview")
@login_required
def sync_preview():
    err = _require_data_manager()
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    project_ids = payload.get("project_ids") or []
    site_ids = payload.get("site_ids") or []

    try:
        from app.utils import va_odk_fetch_instance_ids, va_odk_delta_count
        from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

        scoped = dm_scoped_forms(current_user)
        matched = filter_scoped_forms(scoped, project_ids, site_ids)
        if not matched:
            return jsonify({
                "totals": {
                    "forms": 0, "local_submissions": 0, "odk_submissions": 0,
                    "new_fetch_candidates": 0, "missing_in_odk_flags": 0, "updated_candidates": 0,
                },
                "forms": [],
            })

        forms_preview = []
        totals = {
            "forms": len(matched), "local_submissions": 0, "odk_submissions": 0,
            "new_fetch_candidates": 0, "missing_in_odk_flags": 0, "updated_candidates": 0,
        }

        for form in matched:
            local_sids = set(
                db.session.scalars(
                    sa.select(VaSubmissions.va_sid).where(
                        VaSubmissions.va_form_id == form["form_id"]
                    )
                ).all()
            )
            if not form["odk_project_id"] or not form["odk_form_id"]:
                forms_preview.append({
                    "form_id": form["form_id"], "project_id": form["project_id"],
                    "site_id": form["site_id"], "site_name": form["site_name"],
                    "last_synced_at": form["last_synced_at"],
                    "local_submissions": len(local_sids), "odk_submissions": 0,
                    "new_fetch_candidates": 0, "missing_in_odk_flags": 0,
                    "updated_candidates": None, "preview_status": "unmapped",
                })
                totals["local_submissions"] += len(local_sids)
                continue

            client = va_odk_clientsetup(project_id=form["project_id"])
            odk_ids = va_odk_fetch_instance_ids(
                SimpleNamespace(
                    form_id=form["form_id"], project_id=form["project_id"],
                    odk_project_id=form["odk_project_id"], odk_form_id=form["odk_form_id"],
                ),
                client=client,
            )
            form_id_lower = form["form_id"].lower()
            expected = {f"{iid}-{form_id_lower}" for iid in odk_ids}
            missing_locally = max(len(expected - local_sids), 0)
            missing_in_odk = max(len(local_sids - expected), 0)
            updated_candidates = None
            if form["last_synced_at"]:
                try:
                    updated_candidates = va_odk_delta_count(
                        odk_project_id=int(form["odk_project_id"]),
                        odk_form_id=form["odk_form_id"],
                        since=datetime.fromisoformat(form["last_synced_at"]),
                        app_project_id=form["project_id"],
                        client=client,
                    )
                except Exception:
                    updated_candidates = None

            forms_preview.append({
                "form_id": form["form_id"], "project_id": form["project_id"],
                "site_id": form["site_id"], "site_name": form["site_name"],
                "last_synced_at": form["last_synced_at"],
                "local_submissions": len(local_sids), "odk_submissions": len(odk_ids),
                "new_fetch_candidates": missing_locally, "missing_in_odk_flags": missing_in_odk,
                "updated_candidates": updated_candidates, "preview_status": "ok",
            })
            totals["local_submissions"] += len(local_sids)
            totals["odk_submissions"] += len(odk_ids)
            totals["new_fetch_candidates"] += missing_locally
            totals["missing_in_odk_flags"] += missing_in_odk
            if updated_candidates is not None:
                totals["updated_candidates"] += updated_candidates

        return jsonify({"totals": totals, "forms": forms_preview})
    except Exception as exc:
        log.error("sync_preview failed", exc_info=True)
        return jsonify({"error": str(exc)}), 500


@bp.get("/sync/runs")
@login_required
def sync_runs():
    err = _require_data_manager()
    if err:
        return err

    scoped_form_ids = {f["form_id"] for f in dm_scoped_forms(current_user)}
    runs = db.session.scalars(
        sa.select(VaSyncRun)
        .where(VaSyncRun.triggered_by == "data-manager")
        .order_by(VaSyncRun.started_at.desc())
        .limit(25)
    ).all()

    return jsonify({
        "runs": [
            {
                "sync_run_id": str(run.sync_run_id),
                "target": sync_run_target_label(run),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "status": run.status,
                "records_added": run.records_added,
                "records_updated": run.records_updated,
                "error_message": run.error_message,
                "entries": sync_run_entries(run)[-6:],
            }
            for run in runs
            if (
                run.triggered_user_id == current_user.user_id
                or sync_run_target_label(run) in scoped_form_ids
            )
        ]
    })


@bp.get("/project-site-submissions")
@login_required
def project_site_submissions():
    err = _require_data_manager()
    if err:
        return err

    return jsonify({
        "stats": dm_project_site_submission_stats(current_user),
        "timezone": getattr(current_user, "timezone", "Asia/Kolkata") or "Asia/Kolkata",
    })


@bp.post("/submissions/<va_sid>/sync")
@login_required
def sync_submission(va_sid: str):
    err = _require_data_manager()
    if err:
        return err

    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        return jsonify({"error": "Submission not found."}), 404

    form_row = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).where(
            VaForms.form_id == submission.va_form_id
        )
    ).first()
    if not form_row or not current_user.has_data_manager_submission_access(
        form_row.project_id, form_row.site_id
    ):
        return jsonify({"error": "You do not have access to sync this submission."}), 403

    try:
        from app.tasks.sync_tasks import run_single_submission_sync

        if current_app.extensions.get("celery") is None:
            return jsonify({"error": "Celery is not configured."}), 503

        task = run_single_submission_sync.delay(
            va_sid=va_sid,
            triggered_by="data-manager",
            user_id=str(current_user.user_id),
        )
        audit_dm_submission_action(
            va_sid, "data_manager_requested_submission_refresh", operation="u"
        )
        return jsonify({"message": f"Refresh started for submission {va_sid}.", "task_id": task.id}), 202
    except Exception as exc:
        log.error("sync_submission failed for %s", va_sid, exc_info=True)
        return jsonify({"error": str(exc)}), 500
