"""Coder workflow JSON API — /api/v1/coding/"""

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user
from werkzeug.exceptions import RequestEntityTooLarge

from app import db, limiter
from app.decorators import role_required
from app.models import VaForms, VaProjectSites, VaStatuses, VaSubmissionWorkflow, VaSubmissions
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_demo_history,
    get_coder_output_summary,
    get_coder_project_options,
    get_coder_project_ids,
    get_coder_recodeable_sids,
)

from app.services.coder_workflow_service import (
    AllocationError,
    admin_override_to_recode,
    allocate_own_case,
    allocate_pick_form,
    allocate_random_form,
    get_coder_ready_stats,
    get_pick_available_forms,
    is_upstream_recode,
    require_active_coding_allocation,
    mark_reviewer_eligible_after_recode_window_submissions,
    release_own_coding_allocation,
    _narration_language_filter,
    start_demo_allocation,
    start_recode_allocation,
)
from app.routes.api.request_helpers import error as api_error, intake_error, parse_body
from app.services import smartva_service
from app.services.authz import Action, Reason, can
from app.services.coder_cod_service import (
    CoderCodingError,
    submit_coder_final_cod,
    submit_coder_initial_cod,
    submit_coder_not_codeable,
)
from app.services.case_transition_service import WebIntakeError
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.interview_send_back_service import send_back_for_revision
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.workflow.definition import CODER_READY_POOL_STATES
from app.services.demo_project_service import should_use_demo_actiontype_for_submission
from app.services.workflow.intake_modes import split_form_ids_by_coding_intake_mode
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import admin_actor

bp = Blueprint("coding_api", __name__)


def _filter_forms_by_project(form_ids: list[str], project_id: str) -> list[str]:
    """Return form_ids that belong to the given project."""
    rows = db.session.scalars(
        sa.select(VaForms.form_id).where(
            VaForms.form_id.in_(form_ids),
            VaForms.project_id == project_id,
        )
    ).all()
    return list(rows)


# ---------------------------------------------------------------------------
# GET /api/v1/coding/allocation  — current active allocation
# ---------------------------------------------------------------------------

@bp.get("/allocation")
@role_required("coder", "coding_tester", "admin")
def get_allocation():
    """Return the current active coding allocation, or null.

    Null too for an allocation now outside the user's coding scope: the
    dashboard loads this alongside its other panels and must not fail on it.
    """
    try:
        va_sid = require_active_coding_allocation(current_user)
    except AllocationError:
        va_sid = None
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
@role_required("coder", "coding_tester", "admin")
def allocate():
    """Allocate a form for coding and return the allocation details."""
    body = request.get_json(silent=True) or {}
    sid = body.get("sid")
    is_demo = body.get("demo", False)
    project_id = (body.get("project_id") or "").strip().upper() or None

    try:
        if is_demo:
            if not current_user.is_admin():
                current_app.logger.warning(
                    "coding_allocation_denied reason=demo_requires_admin user_id=%s project_id=%s",
                    current_user.user_id,
                    project_id,
                )
                return api_error("Only admin users can start a demo coding session.", status_code=403)
            result = start_demo_allocation(current_user, project_id)
        elif sid:
            result = allocate_pick_form(current_user, sid)
        else:
            if not (current_user.is_coder() or current_user.is_coding_tester()):
                current_app.logger.warning(
                    "coding_allocation_denied reason=coding_role_required user_id=%s project_id=%s",
                    current_user.user_id,
                    project_id,
                )
                return api_error("Coder or coding tester access is required.", status_code=403)
            result = allocate_random_form(current_user, project_id=project_id)
    except AllocationError as e:
        current_app.logger.warning(
            "coding_allocation_denied reason=allocation_error user_id=%s sid=%s is_demo=%s project_id=%s status_code=%s message=%s",
            current_user.user_id,
            sid,
            is_demo,
            project_id,
            e.status_code,
            e.message,
        )
        return _allocation_error(e)

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


_ALLOCATION_ERROR_CODES = {403: "forbidden", 404: "not_found", 409: "conflict"}


def _allocation_error(e: AllocationError):
    """``{error, code}`` for an AllocationError; a 409 for a case outside the
    pool carries its ``workflow_state`` so the client can decide to retry."""
    extra = {"workflow_state": e.workflow_state} if e.workflow_state else {}
    return api_error(
        e.message, e.code or _ALLOCATION_ERROR_CODES.get(e.status_code, "invalid_request"),
        e.status_code, **extra,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/coding/submissions/<sid>/code-now  — "Code this case now"
# ---------------------------------------------------------------------------

@bp.post("/submissions/<va_sid>/code-now")
@role_required("coder")
def code_now(va_sid):
    """Allocate the caller's own submitted case to them, in a self-coding project
    (docs/policy/coding-workflow-state-machine.md, "Self-coding").

    201 ``{va_sid, actiontype}`` (``vapickcoding``); 200 with ``varesumecoding``
    when the caller already holds this very case. Errors ``{error, code}``: 404 ``not_found``;
    403 ``forbidden`` (not a self-coding project, not the caller's submitted
    case, outside coding scope) / ``allocation_exists`` (another allocation
    held); 409 ``not_ready`` with ``workflow_state`` (attachments or SmartVA
    pending: retry), ``held_by_another`` or ``not_available`` with
    ``workflow_state``, ``conflict`` (retired or duplicate case)."""
    try:
        result = allocate_own_case(current_user, va_sid)
    except AllocationError as e:
        return _allocation_error(e)
    status = 200 if result.actiontype == "varesumecoding" else 201
    return jsonify({"va_sid": result.va_sid, "actiontype": result.actiontype}), status


# ---------------------------------------------------------------------------
# POST /api/v1/coding/allocation/release  — the coder lets go of their case
# ---------------------------------------------------------------------------

@bp.post("/allocation/release")
@role_required("coder", "coding_tester")
def release_allocation():
    """Release the caller's own active coding allocation (docs/policy/
    coding-allocation-timeouts.md, "Coder release"). 200 ``{va_sid,
    workflow_state}``; 409 ``no_allocation`` when none is held."""
    try:
        va_sid = release_own_coding_allocation(current_user)
    except AllocationError as e:
        return _allocation_error(e)
    return jsonify({"va_sid": va_sid, "workflow_state": get_submission_workflow_state(va_sid)})


# ---------------------------------------------------------------------------
# POST /api/v1/coding/recode/<sid>  — start recode episode
# ---------------------------------------------------------------------------

@bp.post("/recode/<va_sid>")
@role_required("coder", "coding_tester")
def recode(va_sid):
    """Start a recode episode for a finalized submission."""
    try:
        result = start_recode_allocation(current_user, va_sid)
    except AllocationError as e:
        return _allocation_error(e)
    return jsonify({"va_sid": result.va_sid, "actiontype": result.actiontype}), 201


@bp.post("/admin-override-recode/<va_sid>")
@role_required("admin")
def admin_override_recode(va_sid):
    """Return a finalized submission to ready_for_coding for recode."""
    try:
        admin_override_to_recode(current_user, va_sid)
    except AllocationError as e:
        return _allocation_error(e)
    return jsonify({"va_sid": va_sid, "workflow_state": "ready_for_coding"}), 200


@bp.post("/submissions/<va_sid>/send-back")
@role_required("coder", "reviewer")
def send_back(va_sid):
    """Send a finalised web or device interview back to its interviewer for
    revision (docs/policy/interview-revisions.md, rule 3). Body: ``reason_code``
    (``missing_information``, ``inconsistent_answers``,
    ``wrong_respondent_or_case``, ``needs_clarification``). 200
    ``{va_sid, workflow_state, reason_code}``. The coder who finalised it, or a
    reviewer working on or eligible for it, in their scope: 404 unknown, 403
    otherwise; 409 ``not_web_submission`` / ``wrong_state``; 422
    ``invalid_reason``."""
    try:
        reply = send_back_for_revision(current_user, va_sid, reason_code=parse_body().get("reason_code"))
        db.session.commit()
    except WebIntakeError as exc:
        db.session.rollback()
        return intake_error(exc)
    return jsonify(reply)


@bp.post("/submissions/<va_sid>/smartva")
@role_required("coder", "coding_tester", "reviewer", "data_manager", "admin")
@limiter.limit("10 per minute")
def run_smartva(va_sid):
    """Queue a SmartVA run for a case from the coding page's panel
    (docs/policy/coding-workflow-state-machine.md, "SmartVA on completion").

    Body (optional): ``regenerate`` (bool), required ``true`` to replace a
    finished result. Starts a run when the status is ``not_requested`` and
    runs again after ``failed``; a run already ``queued`` or ``running`` is
    not queued twice. 202 ``{va_sid, status}`` (``queued``, or the unchanged
    status of a run in progress). Who may: a coder or coding tester who may
    code the case, a reviewer who may review it, a data manager or admin who
    may triage it (404 unknown, 403 out of scope or a view-only grant); 409 ``wrong_state`` (past coding or a confirmed duplicate)
    / ``already_done`` (a result exists and ``regenerate`` is not true); 422
    ``invalid_request``; 503 ``queue_unavailable``."""
    # A coding-level grant, not VIEW: a viewer-only grant or a coder outside
    # the case's scope may look at it but not start a run. The first action
    # that passes names the requester's role in the audit rows.
    for action, role in (
        (Action.CODE, "vacoder"), (Action.REVIEW, "reviewer"), (Action.TRIAGE, "data_manager")
    ):
        decision = can(current_user, action, va_sid)
        if decision:
            break
    else:
        if decision.reason is Reason.NOT_FOUND:
            return api_error(decision.message, "not_found", 404)
        return api_error(decision.message, "forbidden", 403)
    regenerate = parse_body().get("regenerate", False)
    if not isinstance(regenerate, bool):
        return api_error("regenerate must be true or false.", "invalid_request", 422)
    if not smartva_service.smartva_run_allowed(va_sid):
        return api_error("SmartVA cannot be run for this case.", "wrong_state", 409)
    status = smartva_service.smartva_status(va_sid)
    if status in (smartva_service.SMARTVA_QUEUED, smartva_service.SMARTVA_RUNNING):
        return jsonify({"va_sid": va_sid, "status": status}), 202
    if status == smartva_service.SMARTVA_DONE and not regenerate:
        return api_error("SmartVA already has a result; send regenerate to replace it.", "already_done", 409)
    if not smartva_service.enqueue_smartva(
        va_sid,
        "coding_page",
        regenerate=status != smartva_service.SMARTVA_NOT_REQUESTED,
        requested_by=(str(current_user.user_id), role),
    ):
        return api_error("SmartVA could not be queued; try again.", "queue_unavailable", 503)
    return jsonify({"va_sid": va_sid, "status": smartva_service.SMARTVA_QUEUED}), 202


@bp.post("/reviewer-eligible-after-recode-window")
@role_required("admin")
def mark_reviewer_eligible_after_recode_window():
    """Move coder-finalized submissions into reviewer_eligible after 24 hours."""
    transitioned = mark_reviewer_eligible_after_recode_window_submissions(
        actor=admin_actor(current_user.user_id)
    )
    return jsonify({"reviewer_eligible": transitioned}), 200


# ---------------------------------------------------------------------------
# POST /api/v1/coding/initial|finalize|not-codeable/<sid>  — the coder's writes
# ---------------------------------------------------------------------------

_BODY_CAP = 1_200_000  # the DORIS certificate and its envelopes ride along
_FREE_TEXT_CAP = 4000  # characters: remark, other, each other condition


def _coder_refusal(exc: CoderCodingError):
    """``{error, code}`` for a refused write; blocking gates add ``messages``
    and a changed DORIS certificate adds the reprocessed ``processing``."""
    extra = {}
    if exc.code in ("final_blocked", "invalid_cod"):
        extra["messages"] = exc.messages
    if exc.processing is not None:
        extra["processing"] = exc.processing
    return api_error(exc.message, exc.code, exc.status_code, **extra)


@bp.errorhandler(RequestEntityTooLarge)
def _body_too_large(_exc):
    return api_error("The request body is too large.", "payload_too_large", 413)


def _too_long(*texts: str | None) -> bool:
    return any(text and len(text) > _FREE_TEXT_CAP for text in texts)


def _json_object() -> dict | None:
    """The JSON object body, None when absent or not an object.

    The size cap keys on the path only, so no lookup runs before authz. It
    reads ``Content-Length``: CSRF protection has already built the request
    stream without a limit, so ``request.max_content_length`` cannot enforce
    it. Longer, or no length at all (a chunked body, which would be buffered
    whole), raises ``RequestEntityTooLarge`` for the handler above.
    """
    if request.content_length is None or request.content_length > _BODY_CAP:
        raise RequestEntityTooLarge()
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        return None
    return body if isinstance(body, dict) else None


def _text(body: dict, name: str) -> str | None:
    """The stripped text of *name*, None when absent; ValueError when not text."""
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    return value.strip()


def _doris_fields(body: dict) -> dict:
    """The DORIS envelopes of a body: objects, tokens as text (ValueError otherwise)."""
    for name in ("doris_certificate", "doris_result", "codedit_result"):
        if body.get(name) is not None and not isinstance(body[name], dict):
            raise ValueError(f"{name} must be an object.")
    return {
        "doris_certificate": body.get("doris_certificate"),
        "doris_result": body.get("doris_result"),
        "codedit_result": body.get("codedit_result"),
        "doris_process_token": _text(body, "doris_process_token"),
        "doris_result_digest": _text(body, "doris_result_digest"),
        "doris_client_revision": body.get("doris_client_revision", 0),
    }


def _other_conditions_list(body: dict) -> list[str] | None:
    """Step 1 ``other_conditions``: a list of choices, or one text joined by ``|``."""
    value = body.get("other_conditions")
    if value is None:
        return None
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError("other_conditions must be text or a list of text.")


@bp.post("/initial/<va_sid>")
@role_required("coder", "coding_tester")
def initial(va_sid):
    """Save the coder's masked Step 1. Body: ``immediate_cod`` (not for masked
    DORIS, where Part I line 1 gives it), ``antecedent_cod``,
    ``other_conditions`` (a list from the age group's choices, or one text
    joined by ``|``) and, for masked DORIS, ``doris_certificate``,
    ``doris_result``, ``codedit_result``, ``doris_process_token``,
    ``doris_result_digest``, ``doris_client_revision``. 200 ``{va_sid,
    initial_assessment_id, workflow_state}``. Errors ``{error, code}``: 400
    ``invalid_request`` / ``invalid_cod`` (``messages``) /
    ``invalid_other_conditions``; 403 ``forbidden`` / ``no_allocation``; 404
    ``not_found``; 409 ``not_masked`` / ``wrong_state`` / ``no_payload`` and
    the DORIS conflicts (``DORIS_CERTIFICATE_CHANGED`` carries
    ``processing``); 413 ``too_large``; 422 ``invalid_doris``; 503
    ``who_unavailable`` / ``who_not_configured``; 422 also for an
    ``other_conditions`` item over 4000 characters."""
    body = _json_object()
    if body is None:
        return api_error("A JSON object is required.", "invalid_request", 400)
    try:
        fields = {
            "immediate_cod": _text(body, "immediate_cod"),
            "antecedent_cod": _text(body, "antecedent_cod"),
            "other_conditions": _other_conditions_list(body),
            **_doris_fields(body),
        }
    except ValueError as exc:
        return api_error(str(exc), "invalid_request", 400)
    if _too_long(*(fields["other_conditions"] or [])):
        return api_error("An other condition is too long.", "invalid_request", 422)
    try:
        saved = submit_coder_initial_cod(current_user, va_sid, **fields)
    except CoderCodingError as exc:
        return _coder_refusal(exc)
    return jsonify({
        "va_sid": va_sid,
        "initial_assessment_id": str(saved.assessment.va_iniassess_id),
        "workflow_state": get_submission_workflow_state(va_sid),
    })


@bp.post("/finalize/<va_sid>")
@role_required("coder", "coding_tester")
def finalize(va_sid):
    """Save the coder's final COD. Body: ``conclusive_cod`` (required),
    ``remark``, ``immediate_cod`` and ``other_conditions`` (unmasked simple
    projects), the DORIS fields of ``initial`` (unmasked DORIS), and the
    search telemetry ``cod_search_id``, ``cod_chosen_code``,
    ``cod_chosen_rank``. 200 ``{va_sid, final_assessment_id,
    workflow_state}``. Errors as ``initial``, and 422 ``final_blocked`` with
    every blocking message in ``messages`` (an invalid COD, Narrative QA or
    Social Autopsy not done); 422 ``invalid_request`` for a ``remark`` or
    ``other_conditions`` over 4000 characters; 413 ``too_large`` over 1.2 MB."""
    body = _json_object()
    if body is None:
        return api_error("A JSON object is required.", "invalid_request", 400)
    try:
        conclusive_cod = _text(body, "conclusive_cod")
        fields = {
            "remark": _text(body, "remark"),
            "immediate_cod": _text(body, "immediate_cod"),
            "other_conditions": _text(body, "other_conditions"),
            **_doris_fields(body),
        }
        cod_search_id = _text(body, "cod_search_id")
        cod_chosen_code = _text(body, "cod_chosen_code")
        cod_chosen_rank = body.get("cod_chosen_rank")
        if cod_chosen_rank is not None and (
            not isinstance(cod_chosen_rank, int) or isinstance(cod_chosen_rank, bool)
        ):
            raise ValueError("cod_chosen_rank must be an integer.")
    except ValueError as exc:
        return api_error(str(exc), "invalid_request", 400)
    if not conclusive_cod:
        return api_error("conclusive_cod is required.", "invalid_request", 400)
    if _too_long(fields["remark"], fields["other_conditions"]):
        return api_error("remark or other_conditions is too long.", "invalid_request", 422)
    try:
        saved = submit_coder_final_cod(
            current_user,
            va_sid,
            conclusive_cod=conclusive_cod,
            cod_search_id=cod_search_id,
            cod_chosen_code=cod_chosen_code,
            cod_chosen_rank=cod_chosen_rank,
            **fields,
        )
    except CoderCodingError as exc:
        return _coder_refusal(exc)
    return jsonify({
        "va_sid": va_sid,
        "final_assessment_id": str(saved.assessment.va_finassess_id),
        "workflow_state": get_submission_workflow_state(va_sid),
    })


@bp.post("/not-codeable/<va_sid>")
@role_required("coder", "coding_tester")
def not_codeable(va_sid):
    """Report the case Not Codeable. Body: ``reason`` (``narration_language``,
    ``narration_doesnt_match``, ``no_info``, ``form_is_empty``, ``others``),
    ``other`` (text, required for ``others``). Releases the allocation and
    flags ODK Central for revision (a coding tester's report is not counted and
    the case returns to the pool). 200 ``{va_sid, workflow_state, odk_synced}``
    (``odk_synced``: the ODK Central flag was set). Errors ``{error, code}``:
    400 ``invalid_request``; 403 ``forbidden`` / ``no_allocation``; 404
    ``not_found``; 409 ``wrong_state``; 413 ``too_large`` over 1.2 MB; 422
    ``invalid_request`` for an ``other`` over 4000 characters."""
    body = _json_object()
    if body is None:
        return api_error("A JSON object is required.", "invalid_request", 400)
    try:
        reason = _text(body, "reason")
        other = _text(body, "other")
    except ValueError as exc:
        return api_error(str(exc), "invalid_request", 400)
    if _too_long(other):
        return api_error("other is too long.", "invalid_request", 422)
    try:
        saved = submit_coder_not_codeable(current_user, va_sid, reason=reason or "", other=other)
    except CoderCodingError as exc:
        return _coder_refusal(exc)
    return jsonify({
        "va_sid": va_sid,
        "workflow_state": get_submission_workflow_state(va_sid),
        "odk_synced": saved.odk_synced,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/coding/available  — pick-mode form list
# ---------------------------------------------------------------------------

@bp.get("/available")
@role_required("coder", "coding_tester", "admin")
def available_forms():
    """Return forms available for pick-mode coding."""
    va_form_access = current_user.get_coder_va_forms() | current_user.get_coding_tester_va_forms()
    _, pick_form_ids = split_form_ids_by_coding_intake_mode(va_form_access or [])
    forms = get_pick_available_forms(current_user, pick_form_ids)
    return jsonify({"forms": forms, "count": len(forms)})


# ---------------------------------------------------------------------------
# GET /api/v1/coding/stats  — dashboard KPI counts
# ---------------------------------------------------------------------------

@bp.get("/stats")
@role_required("coder", "coding_tester", "admin")
def stats():
    """Return ready-pool counts and mode flags for the coder dashboard."""
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    kpis = get_coder_ready_stats(current_user, project_id=project_id)
    output_summary = get_coder_output_summary(current_user.user_id, project_id=project_id)
    kpis["completed"] = output_summary["completed"]
    kpis["not_codeable"] = output_summary["not_codeable"]
    return jsonify(kpis)


# ---------------------------------------------------------------------------
# GET /api/v1/coding/history  — coder's completed forms history
# ---------------------------------------------------------------------------

@bp.get("/history")
@role_required("coder", "coding_tester", "admin")
def history():
    """Return the coder's completed coding history with recodeable flags."""
    va_form_access = list(current_user.get_coder_va_forms() | current_user.get_coding_tester_va_forms())
    rows = get_coder_completed_history(current_user, va_form_access)
    recodeable_sids = set(get_coder_recodeable_sids(current_user, va_form_access))
    for row in rows:
        row["recodeable"] = row["va_sid"] in recodeable_sids
    demo_rows = get_coder_demo_history(current_user.user_id)
    for row in demo_rows:
        row["recodeable"] = False
    rows = [*demo_rows, *rows]
    return jsonify({"history": rows, "count": len(rows)})


# ---------------------------------------------------------------------------
# GET /api/v1/coding/projects  — distinct project IDs for current coder
# ---------------------------------------------------------------------------

@bp.get("/projects")
@role_required("coder", "coding_tester", "admin")
def projects():
    """Return distinct project IDs accessible to the current coding user."""
    va_form_access = list(current_user.get_coder_va_forms() | current_user.get_coding_tester_va_forms())
    project_ids = get_coder_project_ids(va_form_access)
    project_options = get_coder_project_options(va_form_access)
    return jsonify({
        "projects": list(project_ids),
        "project_options": project_options,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/coding/debug-stats  — runtime coder visibility diagnostics
# ---------------------------------------------------------------------------

@bp.get("/debug-stats")
@role_required("admin")
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
            .where(
                VaSubmissions.va_form_id.in_(form_ids),
                not_confirmed_duplicate_condition(VaSubmissions.va_sid),
            )
            .group_by(VaSubmissionWorkflow.workflow_state)
            .order_by(VaSubmissionWorkflow.workflow_state)
        ).all()

        ready_filters = [
            VaSubmissions.va_form_id.in_(form_ids),
            VaSubmissionWorkflow.workflow_state.in_(CODER_READY_POOL_STATES),
            submission_is_in_odk(),
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
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
