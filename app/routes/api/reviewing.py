"""Reviewer secondary-coding JSON API."""

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.decorators import role_required
from app.services import coding_search_telemetry_service
from app.services import reviewer_dashboard_service as _svc
from app.services.authz import Action, can
from app.services.cod_entry_mode import project_mode
from app.services.coding_service import get_project_for_submission
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    release_own_reviewing_allocation,
    start_reviewer_coding,
    submit_reviewer_final_cod,
    submit_reviewer_initial_cod,
)
from app.services.workflow.definition import WORKFLOW_REVIEWER_FINALIZED
from app.services.workflow.state_store import get_submission_workflow_state

bp = Blueprint("reviewing_api", __name__)


def _error(
    message: str,
    status_code: int,
    *,
    code: str,
    processing: dict | None = None,
):
    """``{error, code}`` (plus ``processing`` on a changed DORIS certificate)."""
    payload = {"error": message, "code": code}
    if processing is not None:
        payload["processing"] = processing
    return jsonify(payload), status_code


def _refusal(exc: ReviewerCodingError):
    # Every raise site in reviewer_coding_service carries a code.
    return _error(
        exc.message,
        exc.status_code,
        code=exc.code or "invalid_request",
        processing=exc.processing,
    )


def _private(response):
    """``private, no-store``: case identifiers on a shared browser are never cached."""
    response.cache_control.private = True
    response.cache_control.no_store = True
    response.cache_control.max_age = 0
    return response


_MAX_OFFSET = 1_000_000
_MAX_PROJECT_ID = 64


class _BadQuery(ValueError):
    """A query parameter the list routes refuse (400 ``invalid_request``)."""


def _page_args() -> tuple[int, int]:
    """``limit`` (default 50, 1..200) and ``offset`` (>= 0) from the query string."""
    values = []
    for name, default, low, high in (
        ("limit", _svc.DEFAULT_PAGE_SIZE, 1, _svc.MAX_PAGE_SIZE),
        ("offset", 0, 0, _MAX_OFFSET),
    ):
        raw = request.args.get(name)
        if raw is None:
            values.append(default)
            continue
        try:
            value = int(raw)
        except ValueError:
            raise _BadQuery(f"{name} must be a whole number.") from None
        if not low <= value <= high:
            raise _BadQuery(f"{name} must be between {low} and {high}.")
        values.append(value)
    return values[0], values[1]


def _project_arg() -> str | None:
    """The optional ``project_id`` filter, upper-cased as the coder's is."""
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    if project_id and len(project_id) > _MAX_PROJECT_ID:
        raise _BadQuery("project_id is too long.")
    return project_id


@bp.get("/allocation")
@role_required("reviewer")
def get_allocation():
    va_sid = get_active_reviewing_allocation(current_user.user_id)
    # An allocation grants nothing once the submission leaves review scope.
    if va_sid and not can(current_user, Action.REVIEW, va_sid).allowed:
        va_sid = None
    return jsonify({"allocation": {"va_sid": va_sid} if va_sid else None})


@bp.post("/allocation/<va_sid>")
@role_required("reviewer")
def allocate(va_sid):
    try:
        result = start_reviewer_coding(current_user, va_sid)
    except ReviewerCodingError as exc:
        return _refusal(exc)
    return jsonify({"va_sid": result.va_sid, "actiontype": result.actiontype}), 201


@bp.post("/allocation/release")
@role_required("reviewer")
def release_allocation():
    """Release the caller's own active reviewing allocation (docs/policy/
    coding-allocation-timeouts.md, "Reviewer release"). No body. 200 ``{va_sid,
    workflow_state}`` (``reviewer_eligible``); 409 ``no_allocation`` when none is
    held, ``wrong_state`` when the case is no longer in a reviewer session."""
    try:
        va_sid = release_own_reviewing_allocation(current_user)
    except ReviewerCodingError as exc:
        return _refusal(exc)
    return jsonify({"va_sid": va_sid, "workflow_state": get_submission_workflow_state(va_sid)})


@bp.get("/stats")
@role_required("reviewer")
def stats():
    """``{in_scope, completed, available, allocation}`` for the reviewer queue.

    ``in_scope`` and ``completed`` are the web dashboard's counts;
    ``available`` is the size of ``/available``; ``allocation`` the
    ``/allocation`` body. ``project_id`` narrows the three counts."""
    try:
        project_id = _project_arg()
    except _BadQuery as exc:
        return _error(str(exc), 400, code="invalid_request")
    va_sid = _svc.get_scoped_allocation(current_user)
    return _private(jsonify({
        "in_scope": _svc.count_in_scope(current_user, project_id),
        "completed": _svc.count_completed(current_user, project_id),
        "available": _svc.count_available(current_user, project_id),
        "allocation": {"va_sid": va_sid} if va_sid else None,
    }))


@bp.get("/available")
@role_required("reviewer")
def available():
    """The cases ``POST /allocation/<va_sid>`` accepts, paged: ``{cases, count,
    limit, offset, has_more}`` (``count`` is the page's size)."""
    try:
        limit, offset = _page_args()
        project_id = _project_arg()
    except _BadQuery as exc:
        return _error(str(exc), 400, code="invalid_request")
    cases, has_more = _svc.list_available(
        current_user, limit=limit, offset=offset, project_id=project_id
    )
    return _private(jsonify({
        "cases": cases, "count": len(cases), "limit": limit, "offset": offset,
        "has_more": has_more,
    }))


@bp.get("/history")
@role_required("reviewer")
def history():
    """The caller's own finished reviews, newest first, paged: ``{history,
    count, limit, offset, has_more}``. Only cases they may still view."""
    try:
        limit, offset = _page_args()
        project_id = _project_arg()
    except _BadQuery as exc:
        return _error(str(exc), 400, code="invalid_request")
    rows, has_more = _svc.list_history(
        current_user, limit=limit, offset=offset, project_id=project_id
    )
    return _private(jsonify({
        "history": rows, "count": len(rows), "limit": limit, "offset": offset,
        "has_more": has_more,
    }))


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
        return _error("DORIS final submission is too large.", 413, code="too_large")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("A JSON object is required.", 400, code="invalid_request")
    for name in ("conclusive_cod", "remark", "immediate_cod", "other_conditions"):
        if body.get(name) is not None and not isinstance(body[name], str):
            return _error(f"{name} must be text.", 400, code="invalid_request")
    conclusive_cod = (body.get("conclusive_cod") or "").strip()
    remark = (body.get("remark") or "").strip() or None
    immediate_cod = (body.get("immediate_cod") or "").strip() or None
    other_conditions = (body.get("other_conditions") or "").strip() or None
    if not conclusive_cod:
        return _error("conclusive_cod is required.", 400, code="invalid_request")
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
        return _refusal(exc)
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
    project = get_project_for_submission(va_sid)
    masked_doris = project is not None and project_mode(project) == "masked_doris"
    # Masked DORIS Step 1 carries the certificate and its envelopes.
    if masked_doris and (
        request.content_length is None or request.content_length > 1_200_000
    ):
        return _error("DORIS submission is too large.", 413, code="too_large")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("A JSON object is required.", 400, code="invalid_request")
    for name in ("immediate_cod", "antecedent_cod", "other_conditions"):
        if body.get(name) is not None and not isinstance(body[name], str):
            return _error(f"{name} must be text.", 400, code="invalid_request")
    immediate_cod = (body.get("immediate_cod") or "").strip()
    antecedent_cod = (body.get("antecedent_cod") or "").strip()
    other_conditions = (body.get("other_conditions") or "").strip() or None
    # Masked DORIS derives the immediate cause from the certificate.
    if not immediate_cod and not masked_doris:
        return _error("immediate_cod is required.", 400, code="invalid_request")
    if not antecedent_cod:
        return _error("antecedent_cod is required.", 400, code="invalid_request")
    try:
        reviewer_initial = submit_reviewer_initial_cod(
            current_user,
            va_sid,
            immediate_cod=immediate_cod or None,
            antecedent_cod=antecedent_cod,
            other_conditions=other_conditions,
            doris_certificate=body.get("doris_certificate"),
            doris_result=body.get("doris_result"),
            codedit_result=body.get("codedit_result"),
            doris_process_token=body.get("doris_process_token"),
            doris_result_digest=body.get("doris_result_digest"),
            doris_client_revision=body.get("doris_client_revision", 0),
        )
    except ReviewerCodingError as exc:
        return _refusal(exc)
    return jsonify(
        {
            "va_sid": va_sid,
            "reviewer_initial_assessment_id": str(
                reviewer_initial.va_riniassess_id
            ),
        }
    ), 200
