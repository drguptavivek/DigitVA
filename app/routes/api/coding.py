"""Coder workflow JSON API — /api/v1/coding/"""

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models import VaSubmissions
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_project_ids,
    get_coder_recodeable_sids,
)

from app.services.coder_workflow_service import (
    AllocationError,
    allocate_pick_form,
    allocate_random_form,
    get_active_coding_allocation,
    get_coder_ready_stats,
    get_pick_available_forms,
    start_demo_allocation,
    start_recode_allocation,
)
from app.services.project_workflow_service import split_form_ids_by_coding_intake_mode

bp = Blueprint("coding_api", __name__)


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code


# ---------------------------------------------------------------------------
# GET /api/v1/coding/allocation  — current active allocation
# ---------------------------------------------------------------------------

@bp.get("/allocation")
@login_required
def get_allocation():
    """Return the current active coding allocation, or null."""
    va_sid = get_active_coding_allocation(current_user.user_id)
    if not va_sid:
        return jsonify({"allocation": None})
    from app.utils import va_render_serialisedates
    form = db.session.get(VaSubmissions, va_sid)
    row = {
        "va_sid": va_sid,
        "va_uniqueid_masked": form.va_uniqueid_masked if form else None,
        "va_age": form.va_deceased_age if form else None,
        "va_gender": form.va_deceased_gender if form else None,
        "va_form_id": form.va_form_id if form else None,
        "va_submission_date": str(form.va_submission_date.date()) if form and form.va_submission_date else None,
        "va_data_collector": form.va_data_collector if form else None,
        "va_deceased_age": form.va_deceased_age if form else None,
        "va_deceased_gender": form.va_deceased_gender if form else None,
        "actiontype": "varesumecoding",
    }
    return jsonify({"allocation": row})


# ---------------------------------------------------------------------------
# POST /api/v1/coding/allocation  — allocate a form
#
# Body (JSON):
#   {}                          → random allocation
#   {"sid": "<sid>"}            → pick-mode allocation
#   {"demo": true}              → admin demo session
#   {"demo": true, "project_id": "PROJ01"}
# ---------------------------------------------------------------------------

@bp.post("/allocation")
@login_required
def allocate():
    """Allocate a form for coding and return the allocation details."""
    body = request.get_json(silent=True) or {}
    sid = body.get("sid")
    is_demo = body.get("demo", False)
    project_id = (body.get("project_id") or "").strip().upper() or None

    try:
        if is_demo:
            if not current_user.is_admin():
                return _error("Only admin users can start a demo coding session.", 403)
            result = start_demo_allocation(current_user, project_id)
        elif sid:
            result = allocate_pick_form(current_user, sid)
        else:
            if not current_user.is_coder():
                return _error("Coder access is required.", 403)
            result = allocate_random_form(current_user, project_id=project_id)
    except AllocationError as e:
        return _error(e.message, e.status_code)

    form = db.session.get(VaSubmissions, result.va_sid)
    return jsonify({
        "va_sid": result.va_sid,
        "actiontype": result.actiontype,
        "va_uniqueid": form.va_uniqueid_masked if form else None,
        "va_age": form.va_deceased_age if form else None,
        "va_gender": form.va_deceased_gender if form else None,
        "va_form_id": form.va_form_id if form else None,
    }), 201


# ---------------------------------------------------------------------------
# POST /api/v1/coding/recode/<sid>  — start recode episode
# ---------------------------------------------------------------------------

@bp.post("/recode/<va_sid>")
@login_required
def recode(va_sid):
    """Start a recode episode for a finalized submission."""
    if not current_user.is_coder():
        return _error("Coder access is required.", 403)
    try:
        result = start_recode_allocation(current_user, va_sid)
    except AllocationError as e:
        return _error(e.message, e.status_code)
    return jsonify({"va_sid": result.va_sid, "actiontype": result.actiontype}), 201


# ---------------------------------------------------------------------------
# GET /api/v1/coding/available  — pick-mode form list
# ---------------------------------------------------------------------------

@bp.get("/available")
@login_required
def available_forms():
    """Return forms available for pick-mode coding."""
    if not current_user.is_coder() and not current_user.is_admin():
        return _error("Coder access is required.", 403)

    va_form_access = current_user.get_coder_va_forms()
    _, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access or [])
    forms = get_pick_available_forms(current_user, pick_form_ids)
    return jsonify({"forms": forms, "count": len(forms)})


# ---------------------------------------------------------------------------
# GET /api/v1/coding/stats  — dashboard KPI counts
# ---------------------------------------------------------------------------

@bp.get("/stats")
@login_required
def stats():
    """Return ready-pool counts and mode flags for the coder dashboard."""
    if not current_user.is_coder() and not current_user.is_admin():
        return _error("Coder access is required.", 403)

    kpis = get_coder_ready_stats(current_user)
    va_form_access = current_user.get_coder_va_forms() or []
    kpis["completed"] = get_coder_completed_count(current_user.user_id, va_form_access)
    return jsonify(kpis)


# ---------------------------------------------------------------------------
# GET /api/v1/coding/history  — coder's completed forms history
# ---------------------------------------------------------------------------

@bp.get("/history")
@login_required
def history():
    """Return the coder's completed coding history with recodeable flags."""
    if not current_user.is_coder() and not current_user.is_admin():
        return _error("Coder access is required.", 403)

    va_form_access = current_user.get_coder_va_forms() or []
    rows = get_coder_completed_history(current_user.user_id, va_form_access)
    recodeable_sids = set(get_coder_recodeable_sids(current_user.user_id, va_form_access))
    for row in rows:
        row["recodeable"] = row["va_sid"] in recodeable_sids
    return jsonify({"history": rows, "count": len(rows)})


# ---------------------------------------------------------------------------
# GET /api/v1/coding/projects  — distinct project IDs for current coder
# ---------------------------------------------------------------------------

@bp.get("/projects")
@login_required
def projects():
    """Return distinct project IDs accessible to the current coder (admin: for demo selector)."""
    if not current_user.is_coder() and not current_user.is_admin():
        return _error("Coder or admin access is required.", 403)

    va_form_access = current_user.get_coder_va_forms() or []
    project_ids = get_coder_project_ids(va_form_access)
    return jsonify({"projects": list(project_ids)})
