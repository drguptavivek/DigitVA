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
from datetime import datetime, timezone
from types import SimpleNamespace

import sqlalchemy as sa
from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    redirect,
    request,
    send_file,
)
from flask_login import current_user

from app import cache, db, limiter
from app.decorators import role_required
from app.models import VaForms, VaSyncRun, VaSubmissions
from app.services.data_management_service import (
    audit_dm_submission_action,
    dm_accept_upstream_change,
    dm_coded_cod_snapshot_export_csv,
    dm_coder_daily_statistics,
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
from app.services import export_store_service as export_store
from app.services.attachment_store import AttachmentStoreError
from app.services.export_store_service import (
    EXPORT_CONTENT_TYPE,
    UTF8_BOM,
    ExportStoreError,
)
from app.services.submission_analytics_mv import (
    get_dm_kpi_from_mv,
    get_dm_project_site_stats_from_mv,
    refresh_submission_analytics_mv,
)

bp = Blueprint("data_management_api", __name__)
log = logging.getLogger(__name__)
_CACHE_TTL = 300
_EXPORT_CACHE_TTL = 900


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


def _export_filters_from_request() -> dict[str, str | None]:
    return {
        "search": request.args.get("search", ""),
        "project": request.args.get("project", ""),
        "site": request.args.get("site", ""),
        "date_from": request.args.get("date_from") or None,
        "date_to": request.args.get("date_to") or None,
        "odk_status": request.args.get("odk_status", ""),
        "smartva": request.args.get("smartva", ""),
        "age_group": request.args.get("age_group", ""),
        "gender": request.args.get("gender", ""),
        "odk_sync": request.args.get("odk_sync", ""),
        "workflow": request.args.get("workflow", ""),
    }


def _export_cache_ttl_seconds() -> int:
    value = current_app.config.get("DM_EXPORT_CACHE_TTL_SECONDS", _EXPORT_CACHE_TTL)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return _EXPORT_CACHE_TTL


def _csv_response(csv_text: str, filename: str, cache_status: str) -> Response:
    """The CSV inline. Only a fallback now — see ``_deliver_export``."""
    return Response(
        UTF8_BOM + csv_text,
        content_type=EXPORT_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Export-Cache": cache_status,
        },
    )


def _deliver_export(ref, filename: str, cache_status: str) -> Response | None:
    """Hand one stored export to the browser, or None when it cannot be.

    On the S3 store that is a ``302`` to a presigned ``attachment`` GET, so the
    CSV never passes through this app server. On the local store it is the
    stored file. Both are ``private, no-store``: an export is scoped to the one
    data manager who asked for it and must not be cached by a proxy.
    """
    url = export_store.presigned_download_url(ref, filename)
    if url:
        response = redirect(url, code=302)
    else:
        path = export_store.export_local_path(ref)
        if path is None:
            return None
        response = send_file(
            path,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Export-Cache"] = cache_status
    return response


def _serve_cached_export_csv(export_kind: str, filename_prefix: str, export_fn) -> Response:
    """Serve one filtered CSV export for the signed-in data manager.

    The export object in the store *is* the cache: a still-fresh object for the
    same kind, user and filters is reused rather than recomputed, exactly as
    the old on-disk cache did, and the ``user_id`` in the key means a lookup
    can never reach another user's export. A store failure is never fatal — the
    CSV is already in hand, so it is sent inline and only the caching is lost.
    """
    filters = _export_filters_from_request()
    ttl_seconds = _export_cache_ttl_seconds()
    filename = f"{filename_prefix}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.csv"

    ref = export_store.export_cache_lookup(
        export_kind=export_kind,
        user_id=current_user.user_id,
        filters=filters,
        ttl_seconds=ttl_seconds,
    )
    if ref is not None:
        response = _deliver_export(ref, filename, cache_status="HIT")
        if response is not None:
            return response

    csv_text = export_fn(current_user, **filters)
    try:
        ref = export_store.write_export(
            export_kind=export_kind,
            user_id=current_user.user_id,
            filters=filters,
            csv_text=csv_text,
        )
    except (ExportStoreError, AttachmentStoreError, OSError) as exc:
        log.warning("Export store write failed for kind=%s: %s", export_kind, exc)
        return _csv_response(csv_text, filename, cache_status="BYPASS")

    response = _deliver_export(ref, filename, cache_status="MISS")
    if response is None:
        return _csv_response(csv_text, filename, cache_status="BYPASS")
    return response


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
    return _serve_cached_export_csv(
        export_kind="submissions",
        filename_prefix="data-management-submissions",
        export_fn=dm_submissions_export_csv,
    )


@bp.get("/submissions/export-smartva-input.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_smartva_input_csv():
    return _serve_cached_export_csv(
        export_kind="smartva_input",
        filename_prefix="data-management-smartva-input",
        export_fn=dm_smartva_input_export_csv,
    )


@bp.get("/submissions/export-smartva-results.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_smartva_results_csv():
    return _serve_cached_export_csv(
        export_kind="smartva_results",
        filename_prefix="data-management-smartva-results",
        export_fn=dm_smartva_results_export_csv,
    )


@bp.get("/submissions/export-smartva-likelihoods.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_smartva_likelihoods_csv():
    return _serve_cached_export_csv(
        export_kind="smartva_likelihoods",
        filename_prefix="data-management-smartva-likelihoods",
        export_fn=dm_smartva_likelihoods_export_csv,
    )


@bp.get("/submissions/export-coded-cod-snapshot.csv")
@role_required("data_manager")
@limiter.limit("30 per minute")
def submissions_export_coded_cod_snapshot_csv():
    return _serve_cached_export_csv(
        export_kind="coded_cod_snapshot",
        filename_prefix="data-management-coded-cod-snapshot",
        export_fn=dm_coded_cod_snapshot_export_csv,
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


@bp.get("/coder-daily-stats")
@role_required("data_manager")
@limiter.limit("120 per minute")
def coder_daily_stats():
    filters = _export_filters_from_request()
    return jsonify(
        _cached(
            "coder_daily_stats",
            lambda: dm_coder_daily_statistics(
                current_user,
                **filters,
                days=7,
                timezone_name=getattr(current_user, "timezone", "Asia/Kolkata"),
            ),
        )
    )


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
        return jsonify({"error": "Operation failed. Check server logs."}), 500


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
        return jsonify({"error": "Operation failed. Check server logs."}), 500


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
        return jsonify({"error": "Operation failed. Check server logs."}), 500


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
        return jsonify({"error": "Operation failed. Check server logs."}), 500

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
        return jsonify({"error": "Operation failed. Check server logs."}), 500


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
        return jsonify({"error": "Operation failed. Check server logs."}), 500


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
        return jsonify({"error": "Operation failed. Check server logs."}), 500


# ---------------------------------------------------------------------------
# Organization routing: the unrouted queue
#
# A health-system project's submissions are attributed to an organization unit
# from the payload's org_<level_code>_code fields at sync time. Submissions
# that nothing in the payload resolved land here: either unrouted entirely, or
# sitting on the ODK mapping's fallback unit rather than their own. A data
# manager pins the right unit by hand, and that pin outranks later syncs.
# Policy: docs/policy/organization-model.md.
# ---------------------------------------------------------------------------

UNROUTED_QUEUE_MAX_ROWS = 200


def _dm_submission_scope_filter():
    """WHERE clause limiting submissions to the current DM's granted scope."""
    project_ids = current_user.get_data_manager_projects()
    project_site_pairs = current_user.get_data_manager_project_sites()
    conditions = []
    if project_ids:
        conditions.append(VaForms.project_id.in_(sorted(project_ids)))
    if project_site_pairs:
        conditions.append(
            sa.tuple_(VaForms.project_id, VaForms.site_id).in_(sorted(project_site_pairs))
        )
    if not conditions:
        return sa.false()
    return sa.or_(*conditions)


@bp.get("/submissions/unrouted")
@role_required("data_manager")
@limiter.limit("120 per minute")
def unrouted_submissions():
    """Submissions in the DM's scope that are not attributed to their own unit.

    ``include=fallback`` (the default) also lists submissions sitting on their
    ODK mapping's fallback unit; ``include=unrouted`` lists only the ones with
    no unit at all.
    """
    from app.models import MasOrgLevel, MasOrgUnit
    from app.services.org_unit_routing_service import RESOLUTION_MAPPING_FALLBACK

    include = (request.args.get("include") or "fallback").strip().lower()
    if include not in {"fallback", "unrouted"}:
        return jsonify({"error": "include must be 'fallback' or 'unrouted'."}), 400

    # Only projects that actually have a tree can have a routing problem.
    project_has_tree = sa.exists(
        sa.select(1).where(
            MasOrgLevel.project_id == VaForms.project_id,
            MasOrgLevel.is_active.is_(True),
        )
    )
    unit = sa.orm.aliased(MasOrgUnit)
    routing_condition = (
        VaSubmissions.org_unit_id.is_(None)
        if include == "unrouted"
        else sa.or_(
            VaSubmissions.org_unit_id.is_(None),
            VaSubmissions.org_unit_resolution == RESOLUTION_MAPPING_FALLBACK,
        )
    )

    project_id = (request.args.get("project") or "").strip()
    stmt = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.va_submission_date,
            VaSubmissions.va_data_collector,
            VaSubmissions.org_unit_resolution,
            VaForms.project_id,
            VaForms.site_id,
            unit.unit_code,
            unit.unit_name,
        )
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(unit, unit.org_unit_id == VaSubmissions.org_unit_id)
        .where(
            _dm_submission_scope_filter(),
            project_has_tree,
            routing_condition,
        )
        .order_by(VaSubmissions.va_submission_date.desc())
        .limit(UNROUTED_QUEUE_MAX_ROWS + 1)
    )
    if project_id:
        stmt = stmt.where(VaForms.project_id == project_id)

    rows = db.session.execute(stmt).all()
    truncated = len(rows) > UNROUTED_QUEUE_MAX_ROWS
    return jsonify({
        "submissions": [
            {
                "va_sid": row.va_sid,
                "submission_date": row.va_submission_date.isoformat()
                if row.va_submission_date
                else None,
                "data_collector": row.va_data_collector,
                "project_id": row.project_id,
                "site_id": row.site_id,
                "resolution": row.org_unit_resolution,
                "unit_code": row.unit_code,
                "unit_name": row.unit_name,
            }
            for row in rows[:UNROUTED_QUEUE_MAX_ROWS]
        ],
        "truncated": truncated,
        "limit": UNROUTED_QUEUE_MAX_ROWS,
    })


@bp.post("/submissions/<path:va_sid>/org-unit")
@role_required("data_manager")
def set_submission_org_unit(va_sid: str):
    """Pin a submission to an organization unit, or clear an existing pin.

    Body ``{"org_unit_id": "<uuid>"}`` pins; ``{"org_unit_id": null}`` clears
    the pin so the next sync routes the submission from its payload again.
    """
    from app.services.org_unit_routing_service import clear_pin, pin_submission_org_unit
    from app.services.organization_service import OrganizationError

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
        return jsonify({"error": "You do not have access to this submission."}), 403

    payload = request.get_json(silent=True) or {}
    raw_unit_id = payload.get("org_unit_id")

    try:
        if raw_unit_id in (None, ""):
            clear_pin(submission)
            action = "data_manager_cleared_submission_org_unit_pin"
            message = "Unit pin cleared. The next sync will route this submission again."
            unit_code = None
        else:
            unit = pin_submission_org_unit(
                submission,
                raw_unit_id,
                actor_user_id=current_user.user_id,
                project_id=form_row.project_id,
            )
            action = "data_manager_pinned_submission_org_unit"
            message = f"Submission pinned to {unit.unit_code}."
            unit_code = unit.unit_code
    except OrganizationError as exc:
        return jsonify({"error": str(exc)}), 400

    audit_dm_submission_action(va_sid, action, operation="u")
    db.session.commit()
    return jsonify({
        "va_sid": va_sid,
        "org_unit_id": str(submission.org_unit_id) if submission.org_unit_id else None,
        "unit_code": unit_code,
        "resolution": submission.org_unit_resolution,
        "message": message,
    })
