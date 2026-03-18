"""Data management blueprint — /data-management/

All routes scoped to the data_manager role: dashboard, sync operations, and
submission-level actions.
"""

import json
import re
import uuid
from types import SimpleNamespace
import logging
from datetime import datetime, timedelta

import pytz
import sqlalchemy as sa
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

from app import db
from app.models import (
    VaSubmissions,
    VaSubmissionAttachments,
    VaSmartvaResults,
    VaStatuses,
    VaDataManagerReview,
    VaForms,
    VaSyncRun,
    VaSiteMaster,
    VaSubmissionWorkflow,
    VaSubmissionsAuditlog,
)
from app.models.map_project_site_odk import MapProjectSiteOdk
from app.services.submission_analytics_mv import get_dm_kpi_from_mv
from app.services.odk_connection_guard_service import guarded_odk_call
from app.services.odk_review_service import resolve_odk_instance_id
from app.utils import va_odk_clientsetup, va_render_serialisedates
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

data_management = Blueprint("data_management", __name__)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit_data_manager_submission_action(
    va_sid: str,
    action: str,
    *,
    operation: str = "r",
) -> None:
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="data_manager",
            va_audit_by=current_user.user_id,
            va_audit_operation=operation,
            va_audit_action=action,
            va_audit_entityid=uuid.uuid4(),
        )
    )
    db.session.commit()


def _data_manager_scope_filter(user):
    project_ids = sorted(user.get_data_manager_projects())
    project_site_pairs = user.get_data_manager_project_sites()

    project_scope_exists = sa.false()
    if project_ids:
        project_scope_exists = VaForms.project_id.in_(project_ids)

    project_site_scope_exists = sa.false()
    if project_site_pairs:
        project_site_scope_exists = sa.tuple_(
            VaForms.project_id, VaForms.site_id
        ).in_(list(project_site_pairs))

    return sa.or_(project_scope_exists, project_site_scope_exists)


def _data_manager_form_in_scope(user, form_id: str) -> bool:
    row = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).where(VaForms.form_id == form_id)
    ).first()
    if not row:
        return False
    return user.has_data_manager_submission_access(row.project_id, row.site_id)


def _data_manager_scoped_forms(user) -> list[dict]:
    scope_filter = _data_manager_scope_filter(user)
    return [
        {
            "form_id": row.form_id,
            "project_id": row.project_id,
            "site_id": row.site_id,
            "site_name": row.site_name or row.site_id,
            "odk_project_id": row.odk_project_id,
            "odk_form_id": row.odk_form_id,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        }
        for row in db.session.execute(
            sa.select(
                VaForms.form_id,
                VaForms.project_id,
                VaForms.site_id,
                VaSiteMaster.site_name,
                MapProjectSiteOdk.odk_project_id,
                MapProjectSiteOdk.odk_form_id,
                MapProjectSiteOdk.last_synced_at,
            )
            .select_from(VaForms)
            .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaForms.site_id)
            .outerjoin(
                MapProjectSiteOdk,
                sa.and_(
                    MapProjectSiteOdk.project_id == VaForms.project_id,
                    MapProjectSiteOdk.site_id == VaForms.site_id,
                ),
            )
            .where(scope_filter)
            .order_by(VaForms.project_id, VaForms.site_id, VaForms.form_id)
        ).mappings().all()
    ]


def _data_manager_odk_edit_url(user, va_sid: str) -> str | None:
    row = db.session.execute(
        sa.select(
            VaSubmissions.va_sid,
            VaForms.project_id,
            VaForms.site_id,
            MapProjectSiteOdk.odk_project_id,
            MapProjectSiteOdk.odk_form_id,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(
            MapProjectSiteOdk,
            sa.and_(
                MapProjectSiteOdk.project_id == VaForms.project_id,
                MapProjectSiteOdk.site_id == VaForms.site_id,
            ),
        )
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    if not row:
        return None
    if not user.has_data_manager_submission_access(row.project_id, row.site_id):
        return None
    if not row.odk_project_id or not row.odk_form_id:
        return None
    client = va_odk_clientsetup(project_id=row.project_id)
    instance_id = resolve_odk_instance_id(row.va_sid)
    response = guarded_odk_call(
        lambda: client.session.get(
            f"projects/{int(row.odk_project_id)}/forms/{row.odk_form_id}/submissions/{instance_id}/edit",
            allow_redirects=False,
        ),
        client=client,
    )
    if response is None:
        return None
    location = response.headers.get("Location")
    if not location:
        return None
    return location


def _filter_scoped_forms(
    scoped_forms: list[dict],
    project_ids: list[str] | None,
    site_ids: list[str] | None,
) -> list[dict]:
    selected_projects = set(project_ids or [])
    selected_sites = set(site_ids or [])
    return [
        form
        for form in scoped_forms
        if (not selected_projects or form["project_id"] in selected_projects)
        and (not selected_sites or form["site_id"] in selected_sites)
    ]


def _data_manager_project_site_submission_stats(user) -> list[dict]:
    scope_filter = _data_manager_scope_filter(user)
    tz_name = getattr(user, "timezone", "Asia/Kolkata") or "Asia/Kolkata"
    user_tz = pytz.timezone(tz_name)
    now_local = datetime.now(user_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_local = today_start_local - timedelta(days=today_start_local.weekday())
    today_start_utc = today_start_local.astimezone(pytz.UTC)
    week_start_utc = week_start_local.astimezone(pytz.UTC)

    return [
        {
            "project_id": row["project_id"],
            "site_id": row["site_id"],
            "total_submissions": row["total_submissions"] or 0,
            "this_week_submissions": row["this_week_submissions"] or 0,
            "today_submissions": row["today_submissions"] or 0,
        }
        for row in db.session.execute(
            sa.select(
                VaForms.project_id,
                VaForms.site_id,
                sa.func.count(VaSubmissions.va_sid).label("total_submissions"),
                sa.func.sum(
                    sa.case(
                        (VaSubmissions.va_submission_date >= week_start_utc, 1),
                        else_=0,
                    )
                ).label("this_week_submissions"),
                sa.func.sum(
                    sa.case(
                        (VaSubmissions.va_submission_date >= today_start_utc, 1),
                        else_=0,
                    )
                ).label("today_submissions"),
            )
            .select_from(VaSubmissions)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .where(scope_filter)
            .group_by(VaForms.project_id, VaForms.site_id)
            .order_by(VaForms.project_id, VaForms.site_id)
        ).mappings().all()
    ]


def _sync_run_target_label(run: VaSyncRun) -> str | None:
    if not run.progress_log:
        return None
    try:
        entries = json.loads(run.progress_log)
    except Exception:
        return None
    if not entries:
        return None
    match = re.match(r"^\[([^\]]+)\]", entries[0].get("msg", ""))
    return match.group(1) if match else None


def _sync_run_entries(run: VaSyncRun) -> list[dict]:
    if not run.progress_log:
        return []
    try:
        entries = json.loads(run.progress_log)
        return entries if isinstance(entries, list) else []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@data_management.get("/")
@login_required
def dashboard():
    if not current_user.is_data_manager():
        va_permission_abortwithflash("Data-manager access is required.", 403)

    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()
    if not project_ids and not project_site_pairs:
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    scope_filter = _data_manager_scope_filter(current_user)
    kpi = get_dm_kpi_from_mv(
        project_ids=project_ids,
        project_site_pairs=project_site_pairs,
    )
    total_submissions = kpi["total_submissions"]
    flagged_submissions = kpi["flagged_submissions"]
    odk_has_issues_submissions = kpi["odk_has_issues_submissions"]
    smartva_missing_submissions = kpi["smartva_missing_submissions"]
    attachment_counts = (
        sa.select(
            VaSubmissionAttachments.va_sid.label("va_sid"),
            sa.func.count().label("attachment_count"),
        )
        .where(VaSubmissionAttachments.exists_on_odk.is_(True))
        .group_by(VaSubmissionAttachments.va_sid)
        .subquery()
    )
    smartva_active_results = (
        sa.select(VaSmartvaResults.va_sid.label("va_sid"))
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .group_by(VaSmartvaResults.va_sid)
        .subquery()
    )
    _mv_ref = sa.table(
        "va_submission_analytics_mv",
        sa.column("va_sid"),
        sa.column("analytics_age_band"),
    )
    submission_rows = [
        va_render_serialisedates(
            row,
            ["va_submission_date", "va_dmreview_createdat"],
        )
        for row in db.session.execute(
            sa.select(
                VaSubmissions.va_sid,
                VaSubmissions.va_uniqueid_masked,
                VaForms.project_id,
                VaForms.site_id,
                sa.func.date(VaSubmissions.va_submission_date).label(
                    "va_submission_date"
                ),
                VaSubmissions.va_data_collector,
                sa.func.coalesce(
                    attachment_counts.c.attachment_count, 0
                ).label("attachment_count"),
                smartva_active_results.c.va_sid.label("smartva_result_sid"),
                VaSubmissions.va_odk_reviewstate,
                VaSubmissions.va_odk_reviewcomments,
                VaSubmissions.va_sync_issue_code,
                VaSubmissions.va_sync_issue_updated_at,
                VaSubmissionWorkflow.workflow_state,
                VaDataManagerReview.va_dmreview_createdat,
                _mv_ref.c.analytics_age_band,
                VaSubmissions.va_deceased_gender,
            )
            .select_from(VaSubmissions)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .join(
                VaSubmissionWorkflow,
                VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                attachment_counts,
                attachment_counts.c.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                smartva_active_results,
                smartva_active_results.c.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                VaDataManagerReview,
                sa.and_(
                    VaDataManagerReview.va_sid == VaSubmissions.va_sid,
                    VaDataManagerReview.va_dmreview_status == VaStatuses.active,
                ),
            )
            .outerjoin(
                _mv_ref,
                _mv_ref.c.va_sid == VaSubmissions.va_sid,
            )
            .where(scope_filter)
            .order_by(
                VaForms.project_id,
                VaForms.site_id,
                VaSubmissions.va_submission_date.desc(),
            )
        ).mappings().all()
    ]
    scoped_forms = _data_manager_scoped_forms(current_user)
    return render_template(
        "va_frontpages/va_data_manager.html",
        total_submissions=total_submissions,
        flagged_submissions=flagged_submissions,
        odk_has_issues_submissions=odk_has_issues_submissions,
        smartva_missing_submissions=smartva_missing_submissions,
        submission_rows=submission_rows,
        scoped_forms=scoped_forms,
    )


@data_management.get("/submissions/<path:va_sid>/odk-edit")
@login_required
def submission_odk_edit(va_sid):
    odk_edit_url = _data_manager_odk_edit_url(current_user, va_sid)
    if not odk_edit_url:
        va_permission_abortwithflash(
            "ODK edit link is not available for this submission.", 404
        )
    _audit_data_manager_submission_action(
        va_sid,
        "data_manager_opened_odk_edit_link",
    )
    from flask import redirect
    return redirect(odk_edit_url)


@data_management.post("/api/forms/<form_id>/sync")
@login_required
def sync_form(form_id: str):
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403
    if not _data_manager_form_in_scope(current_user, form_id):
        return jsonify({"error": "You do not have access to sync this form."}), 403

    try:
        from flask import current_app
        from app.tasks.sync_tasks import run_single_form_sync

        if current_app.extensions.get("celery") is None:
            return jsonify({"error": "Celery is not configured."}), 503

        task = run_single_form_sync.delay(
            form_id=form_id,
            triggered_by="data-manager",
            user_id=str(current_user.user_id),
        )
        return jsonify(
            {
                "message": f"Sync started for form {form_id}.",
                "task_id": task.id,
            }
        ), 202
    except Exception as exc:
        log.error("sync_form failed for %s", form_id, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@data_management.post("/api/sync/preview")
@login_required
def sync_preview():
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403

    payload = request.get_json(silent=True) or {}
    project_ids = payload.get("project_ids") or []
    site_ids = payload.get("site_ids") or []

    try:
        from app.utils import va_odk_fetch_instance_ids, va_odk_delta_count
        from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

        scoped_forms = _data_manager_scoped_forms(current_user)
        matched_forms = _filter_scoped_forms(scoped_forms, project_ids, site_ids)
        if not matched_forms:
            return jsonify(
                {
                    "totals": {
                        "forms": 0,
                        "local_submissions": 0,
                        "odk_submissions": 0,
                        "new_fetch_candidates": 0,
                        "missing_in_odk_flags": 0,
                        "updated_candidates": 0,
                    },
                    "forms": [],
                }
            )

        forms_preview = []
        totals = {
            "forms": len(matched_forms),
            "local_submissions": 0,
            "odk_submissions": 0,
            "new_fetch_candidates": 0,
            "missing_in_odk_flags": 0,
            "updated_candidates": 0,
        }

        for form in matched_forms:
            local_sids = set(
                db.session.scalars(
                    sa.select(VaSubmissions.va_sid).where(
                        VaSubmissions.va_form_id == form["form_id"]
                    )
                ).all()
            )
            if not form["odk_project_id"] or not form["odk_form_id"]:
                forms_preview.append(
                    {
                        "form_id": form["form_id"],
                        "project_id": form["project_id"],
                        "site_id": form["site_id"],
                        "site_name": form["site_name"],
                        "last_synced_at": form["last_synced_at"],
                        "local_submissions": len(local_sids),
                        "odk_submissions": 0,
                        "new_fetch_candidates": 0,
                        "missing_in_odk_flags": 0,
                        "updated_candidates": None,
                        "preview_status": "unmapped",
                    }
                )
                totals["local_submissions"] += len(local_sids)
                continue

            client = va_odk_clientsetup(project_id=form["project_id"])
            odk_ids = va_odk_fetch_instance_ids(
                SimpleNamespace(
                    form_id=form["form_id"],
                    project_id=form["project_id"],
                    odk_project_id=form["odk_project_id"],
                    odk_form_id=form["odk_form_id"],
                ),
                client=client,
            )
            form_id_lower = form["form_id"].lower()
            expected_local_sids = {f"{instance_id}-{form_id_lower}" for instance_id in odk_ids}
            missing_locally = max(len(expected_local_sids - local_sids), 0)
            missing_in_odk = max(len(local_sids - expected_local_sids), 0)
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
            forms_preview.append(
                {
                    "form_id": form["form_id"],
                    "project_id": form["project_id"],
                    "site_id": form["site_id"],
                    "site_name": form["site_name"],
                    "last_synced_at": form["last_synced_at"],
                    "local_submissions": len(local_sids),
                    "odk_submissions": len(odk_ids),
                    "new_fetch_candidates": missing_locally,
                    "missing_in_odk_flags": missing_in_odk,
                    "updated_candidates": updated_candidates,
                    "preview_status": "ok",
                }
            )
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


@data_management.get("/api/sync/runs")
@login_required
def sync_runs():
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403

    scoped_form_ids = {form["form_id"] for form in _data_manager_scoped_forms(current_user)}
    runs = db.session.scalars(
        sa.select(VaSyncRun)
        .where(VaSyncRun.triggered_by == "data-manager")
        .order_by(VaSyncRun.started_at.desc())
        .limit(25)
    ).all()

    return jsonify(
        {
            "runs": [
                {
                    "sync_run_id": str(run.sync_run_id),
                    "target": _sync_run_target_label(run),
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "status": run.status,
                    "records_added": run.records_added,
                    "records_updated": run.records_updated,
                    "error_message": run.error_message,
                    "entries": _sync_run_entries(run)[-6:],
                }
                for run in runs
                if (
                    run.triggered_user_id == current_user.user_id
                    or _sync_run_target_label(run) in scoped_form_ids
                )
            ]
        }
    )


@data_management.get("/api/project-site-submissions")
@login_required
def project_site_submissions():
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403

    return jsonify(
        {
            "stats": _data_manager_project_site_submission_stats(current_user),
            "timezone": getattr(current_user, "timezone", "Asia/Kolkata") or "Asia/Kolkata",
        }
    )


@data_management.post("/api/submissions/<va_sid>/sync")
@login_required
def sync_submission(va_sid: str):
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403

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
        from flask import current_app
        from app.tasks.sync_tasks import run_single_submission_sync

        if current_app.extensions.get("celery") is None:
            return jsonify({"error": "Celery is not configured."}), 503

        task = run_single_submission_sync.delay(
            va_sid=va_sid,
            triggered_by="data-manager",
            user_id=str(current_user.user_id),
        )
        _audit_data_manager_submission_action(
            va_sid,
            "data_manager_requested_submission_refresh",
            operation="u",
        )
        return jsonify(
            {
                "message": f"Refresh started for submission {va_sid}.",
                "task_id": task.id,
            }
        ), 202
    except Exception as exc:
        log.error("sync_submission failed for %s", va_sid, exc_info=True)
        return jsonify({"error": str(exc)}), 500
