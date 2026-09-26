"""Reviewer secondary-coding JSON API."""

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.decorators import role_required
from app.services import coding_search_telemetry_service
from app.services.coding_service import get_project_for_submission
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    start_reviewer_coding,
    submit_reviewer_final_cod,
    submit_reviewer_initial_cod,
)
from app.services.workflow.definition import WORKFLOW_REVIEWER_FINALIZED

bp = Blueprint("reviewing_api", __name__)


def _error(
    message: str,
    status_code: int,
    *,
    code: str | None = None,
    processing: dict | None = None,
):
    if code:
        error = {"code": code, "message": message}
        payload = {"schema_version": 1, "error": error}
        if processing is not None:
            payload["processing"] = processing
        return jsonify(payload), status_code
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
    project = get_project_for_submission(va_sid)
    if (
        project is not None
        and not project.masked_cod_required
        and project.cod_entry_mode == "doris"
        and (request.content_length is None or request.content_length > 1_200_000)
    ):
        return _error("DORIS final submission is too large.", 413)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("A JSON object is required.", 400)
    for name in ("conclusive_cod", "remark", "immediate_cod", "other_conditions"):
        if body.get(name) is not None and not isinstance(body[name], str):
            return _error(f"{name} must be text.", 400)
    conclusive_cod = (body.get("conclusive_cod") or "").strip()
    remark = (body.get("remark") or "").strip() or None
    immediate_cod = (body.get("immediate_cod") or "").strip() or None
    other_conditions = (body.get("other_conditions") or "").strip() or None
    if not conclusive_cod:
        return _error("conclusive_cod is required.", 400)
    try:
        reviewer_final = submit_reviewer_final_cod(
            current_user,
            va_sid,
            conclusive_cod=conclusive_cod,
            remark=remark,
            immediate_cod=immediate_cod,
            other_conditions=other_conditions,
            doris_certificate=body.get("doris_certificate"),
            doris_result=body.get("doris_result"),
            codedit_result=body.get("codedit_result"),
            doris_process_token=body.get("doris_process_token"),
            doris_result_digest=body.get("doris_result_digest"),
            doris_client_revision=body.get("doris_client_revision", 0),
        )
    except ReviewerCodingError as exc:
        return _error(
            exc.message,
            exc.status_code,
            code=exc.code,
            processing=exc.processing,
        )
    # The reviewer's conclusive COD is stored: attach the picked code to the
    # search the browser says produced it (digitva-zpe.3). Never fatal.
    coding_search_telemetry_service.record_choice(
        search_id=body.get("cod_search_id"),
        chosen_code=body.get("cod_chosen_code"),
        chosen_rank=body.get("cod_chosen_rank"),
        role=coding_search_telemetry_service.role_label(current_user),
    )
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
