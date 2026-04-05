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
from flask import Blueprint, Response, jsonify, request, current_app
from flask_login import current_user

from app import cache, db, limiter
from app.decorators import role_required
from app.models import VaForms, VaSyncRun, VaSubmissions
from app.services.data_management_service import (
    audit_dm_submission_action,
    dm_accept_upstream_change,
    dm_filter_options,
    dm_form_in_scope,
    dm_screening_pass,
    dm_screening_reject,
    dm_reject_upstream_change,
    dm_scoped_forms,
    dm_smartva_input_export_csv,
    dm_smartva_likelihoods_export_csv,
    dm_smartva_results_export_csv,
    dm_submissions_export_csv,
    dm_submissions_page,
    dm_upstream_change_details,
    filter_scoped_forms,
    sync_run_entries,
    sync_run_target_label,
)
from app.services.submission_analytics_mv import (
    get_dm_kpi_from_mv,
    get_dm_project_site_stats_from_mv,
    refresh_submission_analytics_mv,
)

bp = Blueprint("data_management_api", __name__)
log = logging.getLogger(__name__)
_CACHE_TTL = 300


def _cache_key(suffix: str) -> str:
    qs = request.query_string.decode()
    return f"dm_analytics:{current_user.user_id}:{suffix}:{qs}"


def _cached(key: str, compute_fn, timeout: int = _CACHE_TTL):
    full_key = _cache_key(key)
    try:
        data = cache.get(full_key)
    except Exception:
        data = None
    if data is not None and not isinstance(data, BaseException):
        return data
    data = compute_fn()
    try:
        cache.set(full_key, data, timeout=timeout)
    except Exception as exc:
        log.warning("Data-manager cache set failed (%s): %s", full_key, exc, exc_info=True)
    return data


def _refresh_dm_dashboard_analytics() -> None:
    """Refresh dashboard analytics after workflow-mutating DM actions."""
    refresh_submission_analytics_mv(concurrently=False)
    try:
        cache.clear()
    except Exception as exc:
        log.warning("Data-manager cache clear failed after analytics refresh: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# GET /api/v1/data-management/submissions  — paginated submission table
# ---------------------------------------------------------------------------

@bp.get("/submissions")
@role_required("data_manager")
@limiter.limit("120 per minute")
def submissions():

    page     = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(10, request.args.get("size", 25, type=int)))

    # Tabulator sends sort as sort[0][field] / sort[0][dir]
    sort_field = request.args.get("sort[0][field]", "va_submission_date")
    sort_dir   = request.args.get("sort[0][dir]", "desc")

    result = dm_submissions_page(
        current_user,
        page=page,
        per_page=per_page,
        search=request.args.get("search", ""),
        project=request.args.get("project", ""),
        site=request.args.get("site", ""),
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        odk_status=request.args.get("odk_status", ""),
        smartva=request.args.get("smartva", ""),
        age_group=request.args.get("age_group", ""),
        gender=request.args.get("gender", ""),
        odk_sync=request.args.get("odk_sync", ""),
        workflow=request.args.get("workflow", ""),
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    return jsonify(result)


@bp.get("/submissions/export.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_csv():

    sort_field = request.args.get("sort[0][field]", "va_submission_date")
    sort_dir = request.args.get("sort[0][dir]", "desc")
    csv_text = dm_submissions_export_csv(
        current_user,
        search=request.args.get("search", ""),
        project=request.args.get("project", ""),
        site=request.args.get("site", ""),
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        odk_status=request.args.get("odk_status", ""),
        smartva=request.args.get("smartva", ""),
        age_group=request.args.get("age_group", ""),
        gender=request.args.get("gender", ""),
        odk_sync=request.args.get("odk_sync", ""),
        workflow=request.args.get("workflow", ""),
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    filename = f"data-management-submissions-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
    return Response(
        "\ufeff" + csv_text,
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@bp.get("/submissions/export-smartva-input.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_smartva_input_csv():

    sort_field = request.args.get("sort[0][field]", "va_submission_date")
    sort_dir = request.args.get("sort[0][dir]", "desc")
    csv_text = dm_smartva_input_export_csv(
        current_user,
        search=request.args.get("search", ""),
        project=request.args.get("project", ""),
        site=request.args.get("site", ""),
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        odk_status=request.args.get("odk_status", ""),
        smartva=request.args.get("smartva", ""),
        age_group=request.args.get("age_group", ""),
        gender=request.args.get("gender", ""),
        odk_sync=request.args.get("odk_sync", ""),
        workflow=request.args.get("workflow", ""),
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    filename = f"data-management-smartva-input-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
    return Response(
        "\ufeff" + csv_text,
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@bp.get("/submissions/export-smartva-results.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_smartva_results_csv():

    sort_field = request.args.get("sort[0][field]", "va_submission_date")
    sort_dir = request.args.get("sort[0][dir]", "desc")
    csv_text = dm_smartva_results_export_csv(
        current_user,
        search=request.args.get("search", ""),
        project=request.args.get("project", ""),
        site=request.args.get("site", ""),
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        odk_status=request.args.get("odk_status", ""),
        smartva=request.args.get("smartva", ""),
        age_group=request.args.get("age_group", ""),
        gender=request.args.get("gender", ""),
        odk_sync=request.args.get("odk_sync", ""),
        workflow=request.args.get("workflow", ""),
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    filename = f"data-management-smartva-results-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
    return Response(
        "\ufeff" + csv_text,
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@bp.get("/submissions/export-smartva-likelihoods.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_smartva_likelihoods_csv():

    sort_field = request.args.get("sort[0][field]", "va_submission_date")
    sort_dir = request.args.get("sort[0][dir]", "desc")
    csv_text = dm_smartva_likelihoods_export_csv(
        current_user,
        search=request.args.get("search", ""),
        project=request.args.get("project", ""),
        site=request.args.get("site", ""),
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        odk_status=request.args.get("odk_status", ""),
        smartva=request.args.get("smartva", ""),
        age_group=request.args.get("age_group", ""),
        gender=request.args.get("gender", ""),
        odk_sync=request.args.get("odk_sync", ""),
        workflow=request.args.get("workflow", ""),
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    filename = f"data-management-smartva-likelihoods-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
    return Response(
        "\ufeff" + csv_text,
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# GET /api/v1/data-management/kpi  — dashboard KPI counts
# ---------------------------------------------------------------------------

@bp.get("/kpi")
@role_required("data_manager")
@limiter.limit("120 per minute")
def kpi():

    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()
    return jsonify(_cached("kpi", lambda:
        get_dm_kpi_from_mv(
            project_ids,
            project_site_pairs,
            project=request.args.get("project", ""),
            site=request.args.get("site", ""),
            date_from=request.args.get("date_from") or None,
            date_to=request.args.get("date_to") or None,
            odk_status=request.args.get("odk_status", ""),
            smartva=request.args.get("smartva", ""),
            age_group=request.args.get("age_group", ""),
            gender=request.args.get("gender", ""),
            odk_sync=request.args.get("odk_sync", ""),
            workflow=request.args.get("workflow", ""),
        )
    ))


# ---------------------------------------------------------------------------
# GET /api/v1/data-management/filter-options  — distinct filter values
# ---------------------------------------------------------------------------

@bp.get("/filter-options")
@role_required("data_manager")
@limiter.limit("120 per minute")
def filter_options():
    return jsonify(dm_filter_options(current_user))


@bp.get("/submissions/<path:va_sid>/upstream-change-details")
@role_required("data_manager", "admin")
@limiter.limit("120 per minute")
def upstream_change_details(va_sid: str):
    try:
        return jsonify(dm_upstream_change_details(current_user, va_sid))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# (existing endpoints below)
# ---------------------------------------------------------------------------

@bp.post("/forms/<form_id>/sync")
@role_required("data_manager")
def sync_form(form_id: str):
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
@role_required("data_manager")
def sync_preview():

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
@role_required("data_manager")
def sync_runs():

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
@role_required("data_manager")
@limiter.limit("120 per minute")
def project_site_submissions():

    timezone_name = getattr(current_user, "timezone", "Asia/Kolkata") or "Asia/Kolkata"
    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()
    return jsonify({
        "stats": get_dm_project_site_stats_from_mv(
            project_ids=project_ids,
            project_site_pairs=project_site_pairs,
            timezone_name=timezone_name,
            project=request.args.get("project", ""),
            site=request.args.get("site", ""),
            date_from=request.args.get("date_from") or None,
            date_to=request.args.get("date_to") or None,
            odk_status=request.args.get("odk_status", ""),
            smartva=request.args.get("smartva", ""),
            age_group=request.args.get("age_group", ""),
            gender=request.args.get("gender", ""),
            odk_sync=request.args.get("odk_sync", ""),
            workflow=request.args.get("workflow", ""),
        ),
        "timezone": timezone_name,
    })


@bp.post("/submissions/<va_sid>/sync")
@role_required("data_manager")
def sync_submission(va_sid: str):

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


# ---------------------------------------------------------------------------
# POST /submissions/<sid>/accept-upstream-change
# POST /submissions/<sid>/reject-upstream-change
# ---------------------------------------------------------------------------

@bp.post("/submissions/<va_sid>/accept-upstream-change")
@role_required("data_manager", "admin")
def accept_upstream_change(va_sid: str):
    """Accept an upstream ODK data change: clear COD artifacts and reopen coding."""
    try:
        dm_accept_upstream_change(current_user, va_sid)
        db.session.commit()
        _refresh_dm_dashboard_analytics()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        log.error("accept_upstream_change failed for %s", va_sid, exc_info=True)
        return jsonify({"error": str(exc)}), 500

    # Fire SmartVA immediately so the submission doesn't wait for the next scheduled sync.
    task_id = None
    try:
        from app.tasks.sync_tasks import run_smartva_for_submission
        if current_app.extensions.get("celery"):
            task = run_smartva_for_submission.delay(va_sid=va_sid, triggered_by="data-manager-accept")
            task_id = task.id
    except Exception:
        log.warning("accept_upstream_change: could not enqueue SmartVA for %s", va_sid, exc_info=True)

    return jsonify({
        "message": "Upstream change accepted for recoding. Submission moved to SmartVA pending.",
        "smartva_task_id": task_id,
    })


@bp.post("/submissions/<va_sid>/screening-pass")
@role_required("data_manager", "admin")
def screening_pass(va_sid: str):
    """Pass a screening-pending submission into SmartVA processing."""
    try:
        dm_screening_pass(current_user, va_sid)
        db.session.commit()
        return jsonify({"message": "Screening passed. Submission moved to SmartVA pending."})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        log.error("screening_pass failed for %s", va_sid, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@bp.post("/submissions/<va_sid>/screening-reject")
@role_required("data_manager", "admin")
def screening_reject(va_sid: str):
    """Reject a screening-pending submission before SmartVA/coding."""
    try:
        dm_screening_reject(current_user, va_sid)
        db.session.commit()
        return jsonify({"message": "Screening rejected. Submission marked not codeable."})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        log.error("screening_reject failed for %s", va_sid, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@bp.post("/submissions/<va_sid>/reject-upstream-change")
@role_required("data_manager", "admin")
def reject_upstream_change(va_sid: str):
    """Keep the current ICD decision while adopting the latest upstream ODK data."""
    try:
        dm_reject_upstream_change(current_user, va_sid)
        db.session.commit()
        _refresh_dm_dashboard_analytics()
        return jsonify({
            "message": (
                "Latest upstream ODK data adopted. Current finalized ICD decision kept."
            )
        })
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        log.error("reject_upstream_change failed for %s", va_sid, exc_info=True)
        return jsonify({"error": str(exc)}), 500
