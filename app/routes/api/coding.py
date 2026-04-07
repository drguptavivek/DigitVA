"""Coder workflow JSON API — /api/v1/coding/"""

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import VaForms, VaProjectSites, VaStatuses, VaSubmissionWorkflow, VaSubmissions
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_project_ids,
    get_coder_recodeable_sids,
)

from app.services.coder_workflow_service import (
    AllocationError,
    admin_override_to_recode,
    allocate_pick_form,
    allocate_random_form,
    get_active_coding_allocation,
    get_coder_ready_stats,
    get_pick_available_forms,
    is_upstream_recode,
    mark_reviewer_eligible_after_recode_window_submissions,
    _narration_language_filter,
    start_demo_allocation,
    start_recode_allocation,
)
from app.services.workflow.definition import CODER_READY_POOL_STATES
from app.services.demo_project_service import should_use_demo_actiontype_for_submission
from app.services.workflow.intake_modes import split_form_ids_by_coding_intake_mode
from app.services.workflow.transitions import admin_actor

bp = Blueprint("coding_api", __name__)


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code


# ---------------------------------------------------------------------------
# GET /api/v1/coding/allocation  — current active allocation
# ---------------------------------------------------------------------------

@bp.get("/allocation")
@role_required("coder", "admin")
def get_allocation():
    """Return the current active coding allocation, or null."""
    va_sid = get_active_coding_allocation(current_user.user_id)
    if not va_sid:
        return jsonify({"allocation": None})
    form = db.session.get(VaSubmissions, va_sid)
    form_meta = None
    if form:
        form_meta = db.session.execute(
            sa.select(VaForms.project_id, VaForms.site_id).where(
                VaForms.form_id == form.va_form_id
            )
        ).first()
    row = {
        "va_sid": va_sid,
        "project_id": form_meta.project_id if form_meta else None,
        "site_id": form_meta.site_id if form_meta else None,
        "va_uniqueid_masked": form.va_uniqueid_masked if form else None,
        "va_age": form.va_deceased_age if form else None,
        "va_gender": form.va_deceased_gender if form else None,
        "va_form_id": form.va_form_id if form else None,
        "va_submission_date": str(form.va_submission_date.date()) if form and form.va_submission_date else None,
        "va_data_collector": form.va_data_collector if form else None,
        "va_deceased_age": form.va_deceased_age if form else None,
        "va_deceased_gender": form.va_deceased_gender if form else None,
        "actiontype": (
            "vademo_start_coding"
            if should_use_demo_actiontype_for_submission(va_sid)
            else "varesumecoding"
        ),
        "is_upstream_recode": is_upstream_recode(va_sid),
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
@role_required("coder", "admin")
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
        "is_upstream_recode": is_upstream_recode(result.va_sid),
    }), 201


# ---------------------------------------------------------------------------
# POST /api/v1/coding/recode/<sid>  — start recode episode
# ---------------------------------------------------------------------------

@bp.post("/recode/<va_sid>")
@role_required("coder")
def recode(va_sid):
    """Start a recode episode for a finalized submission."""
    try:
        result = start_recode_allocation(current_user, va_sid)
    except AllocationError as e:
        return _error(e.message, e.status_code)
    return jsonify({"va_sid": result.va_sid, "actiontype": result.actiontype}), 201


@bp.post("/admin-override-recode/<va_sid>")
@role_required("admin")
def admin_override_recode(va_sid):
    """Return a finalized submission to ready_for_coding for recode."""
    try:
        admin_override_to_recode(current_user, va_sid)
    except AllocationError as e:
        return _error(e.message, e.status_code)
    return jsonify({"va_sid": va_sid, "workflow_state": "ready_for_coding"}), 200


@bp.post("/reviewer-eligible-after-recode-window")
@role_required("admin")
def mark_reviewer_eligible_after_recode_window():
    """Move coder-finalized submissions into reviewer_eligible after 24 hours."""
    transitioned = mark_reviewer_eligible_after_recode_window_submissions(
        actor=admin_actor(current_user.user_id)
    )
    return jsonify({"reviewer_eligible": transitioned}), 200


# ---------------------------------------------------------------------------
# GET /api/v1/coding/available  — pick-mode form list
# ---------------------------------------------------------------------------

@bp.get("/available")
@role_required("coder", "admin")
def available_forms():
    """Return forms available for pick-mode coding."""
    va_form_access = current_user.get_coder_va_forms()
    _, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access or [])
    forms = get_pick_available_forms(current_user, pick_form_ids)
    return jsonify({"forms": forms, "count": len(forms)})


# ---------------------------------------------------------------------------
# GET /api/v1/coding/stats  — dashboard KPI counts
# ---------------------------------------------------------------------------

@bp.get("/stats")
@role_required("coder", "admin")
def stats():
    """Return ready-pool counts and mode flags for the coder dashboard."""
    kpis = get_coder_ready_stats(current_user)
    va_form_access = current_user.get_coder_va_forms() or []
    kpis["completed"] = get_coder_completed_count(current_user.user_id, va_form_access)
    return jsonify(kpis)


# ---------------------------------------------------------------------------
# GET /api/v1/coding/history  — coder's completed forms history
# ---------------------------------------------------------------------------

@bp.get("/history")
@role_required("coder", "admin")
def history():
    """Return the coder's completed coding history with recodeable flags."""
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
@role_required("coder", "admin")
def projects():
    """Return distinct project IDs accessible to the current coder (admin: for demo selector)."""
    va_form_access = current_user.get_coder_va_forms() or []
    project_ids = get_coder_project_ids(va_form_access)
    return jsonify({"projects": list(project_ids)})


# ---------------------------------------------------------------------------
# GET /api/v1/coding/debug-stats  — runtime coder visibility diagnostics
# ---------------------------------------------------------------------------

@bp.get("/debug-stats")
@role_required("coder", "admin")
def debug_stats():
    """Return detailed coder visibility diagnostics for the current session."""
    form_ids = sorted(current_user.get_coder_va_forms() or [])
    random_form_ids, pick_form_ids = split_form_ids_by_coding_intake_mode(form_ids)
    narration_language_filter = _narration_language_filter(current_user)
    language_list = sorted(
        {
            str(language).strip().lower()
            for language in (current_user.vacode_language or [])
            if str(language).strip()
        }
    )

    form_rows = []
    if form_ids:
        form_rows = db.session.execute(
            sa.select(
                VaForms.form_id,
                VaForms.project_id,
                VaForms.site_id,
                VaForms.form_status,
                VaProjectSites.project_site_status,
            )
            .select_from(VaForms)
            .outerjoin(
                VaProjectSites,
                sa.and_(
                    VaProjectSites.project_id == VaForms.project_id,
                    VaProjectSites.site_id == VaForms.site_id,
                ),
            )
            .where(VaForms.form_id.in_(form_ids))
            .order_by(VaForms.project_id, VaForms.site_id, VaForms.form_id)
        ).all()

    state_counts_rows = []
    ready_by_language_rows = []
    ready_by_form_rows = []
    if form_ids:
        state_counts_rows = db.session.execute(
            sa.select(VaSubmissionWorkflow.workflow_state, sa.func.count())
            .select_from(VaSubmissions)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(VaSubmissions.va_form_id.in_(form_ids))
            .group_by(VaSubmissionWorkflow.workflow_state)
            .order_by(VaSubmissionWorkflow.workflow_state)
        ).all()

        ready_filters = [
            VaSubmissions.va_form_id.in_(form_ids),
            VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
        ]
        if narration_language_filter is not None:
            ready_filters.append(narration_language_filter)

        ready_by_language_rows = db.session.execute(
            sa.select(sa.func.lower(VaSubmissions.va_narration_language), sa.func.count())
            .select_from(VaSubmissions)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(sa.and_(*ready_filters))
            .group_by(sa.func.lower(VaSubmissions.va_narration_language))
            .order_by(sa.func.lower(VaSubmissions.va_narration_language))
        ).all()

        ready_by_form_rows = db.session.execute(
            sa.select(VaSubmissions.va_form_id, sa.func.count())
            .select_from(VaSubmissions)
            .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
            .where(sa.and_(*ready_filters))
            .group_by(VaSubmissions.va_form_id)
            .order_by(VaSubmissions.va_form_id)
        ).all()

    return jsonify({
        "user": {
            "user_id": str(current_user.user_id),
            "email": current_user.email,
            "is_admin": bool(current_user.is_admin()),
        },
        "coder_scope": {
            "languages": language_list,
            "form_count": len(form_ids),
            "form_ids": form_ids,
            "random_form_ids": sorted(random_form_ids),
            "pick_form_ids": sorted(pick_form_ids),
        },
        "form_mapping_status": [
            {
                "form_id": row.form_id,
                "project_id": row.project_id,
                "site_id": row.site_id,
                "form_status": row.form_status.value if row.form_status else None,
                "project_site_status": row.project_site_status.value if row.project_site_status else None,
                "project_site_active": row.project_site_status == VaStatuses.active,
            }
            for row in form_rows
        ],
        "workflow_visibility": {
            "coder_ready_pool_states": sorted(CODER_READY_POOL_STATES),
            "state_counts_by_form_scope": [
                {"state": state, "count": count}
                for state, count in state_counts_rows
            ],
            "ready_for_coding_after_language_filter": {
                "count_by_language": [
                    {"language": language, "count": count}
                    for language, count in ready_by_language_rows
                ],
                "count_by_form": [
                    {"form_id": form_id, "count": count}
                    for form_id, count in ready_by_form_rows
                ],
                "total": int(sum(count for _, count in ready_by_form_rows)),
            },
        },
    })
