"""Reviewer secondary-coding JSON API."""

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.decorators import role_required
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    start_reviewer_coding,
    submit_reviewer_initial_cod,
    submit_reviewer_final_cod,
)
from app.services.workflow.definition import WORKFLOW_REVIEWER_FINALIZED


bp = Blueprint("reviewing_api", __name__)


def _error(message: str, status_code: int):
    return jsonify({"error": message}), status_code


@bp.get("/allocation")
@role_required("reviewer")
def get_allocation():
    va_sid = get_active_reviewing_allocation(current_user.user_id)
    return jsonify({"allocation": {"va_sid": va_sid} if va_sid else None})


@bp.post("/allocation/<va_sid>")
@role_required("reviewer")
def allocate(va_sid):
    try:
        result = start_reviewer_coding(current_user, va_sid)
    except ReviewerCodingError as exc:
        return _error(exc.message, exc.status_code)
    return jsonify({"va_sid": result.va_sid, "actiontype": result.actiontype}), 201


@bp.post("/finalize/<va_sid>")
@role_required("reviewer")
def finalize(va_sid):
    body = request.get_json(silent=True) or {}
    conclusive_cod = (body.get("conclusive_cod") or "").strip()
    remark = (body.get("remark") or "").strip() or None
    if not conclusive_cod:
        return _error("conclusive_cod is required.", 400)
    try:
        reviewer_final = submit_reviewer_final_cod(
            current_user,
            va_sid,
            conclusive_cod=conclusive_cod,
            remark=remark,
        )
    except ReviewerCodingError as exc:
        return _error(exc.message, exc.status_code)
    return jsonify(
        {
            "va_sid": va_sid,
            "reviewer_final_assessment_id": str(reviewer_final.va_rfinassess_id),
            "workflow_state": WORKFLOW_REVIEWER_FINALIZED,
        }
    ), 200


@bp.post("/initial/<va_sid>")
@role_required("reviewer")
def initial(va_sid):
    body = request.get_json(silent=True) or {}
    immediate_cod = (body.get("immediate_cod") or "").strip()
    antecedent_cod = (body.get("antecedent_cod") or "").strip()
    other_conditions = (body.get("other_conditions") or "").strip() or None
    if not immediate_cod:
        return _error("immediate_cod is required.", 400)
    if not antecedent_cod:
        return _error("antecedent_cod is required.", 400)
    try:
        reviewer_initial = submit_reviewer_initial_cod(
            current_user,
            va_sid,
            immediate_cod=immediate_cod,
            antecedent_cod=antecedent_cod,
            other_conditions=other_conditions,
        )
    except ReviewerCodingError as exc:
        return _error(exc.message, exc.status_code)
    return jsonify(
        {
            "va_sid": va_sid,
            "reviewer_initial_assessment_id": str(
                reviewer_initial.va_riniassess_id
            ),
        }
    ), 200
