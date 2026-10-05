"""Coding and review workspace content — /api/v1/va/<sid>/workspace, .../categories/<code>, .../note

One call for the workspace shell, one per category, for any client (cookie or
bearer). Authorization comes first and is the one the COD writes use: coding
needs the caller's active coding allocation (``require_coding_session``),
reviewing REVIEW access plus their own active reviewing allocation. The
content itself is ``case_content_service``, which the web partials render
from too. There is no read-only "view" mode yet. The private note takes the
same allocation check without rendering any category.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import VaFinalAssessments, VaStatuses, VaSubmissions
from app.routes.api.request_helpers import error as api_error
from app.services.authz import effective_roles
from app.services.case_content_service import (
    category_block_code,
    coding_step,
    final_blockers,
    get_active_smartva,
    get_case_artifacts,
    get_section_data,
    get_step1_prefill,
    reviewing_step,
    smartva_summary,
    social_autopsy_enabled,
)
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.cod_entry_mode import is_masked
from app.services.cod_entry_mode import project_mode as get_project_mode
from app.services.coder_cod_service import (
    CoderCodingError,
    derive_actiontype,
    other_conditions_choices,
    require_coding_session,
)
from app.services.coding_service import get_project_for_submission
from app.services.field_mapping_service import get_mapping_service
from app.services.final_cod_authority_service import get_active_recode_episode
from app.services.icd_coding_value import DEFAULT_ICD_CLASSIFICATION
from app.services.narrative_qa_service import NARRATIVE_QA_FIELDS, NARRATIVE_QA_MAX_SCORE
from app.services.payload_bound_coding_artifact_service import (
    get_current_payload_narrative_assessment,
    get_current_payload_social_autopsy_analysis,
)
from app.services.reviewer_coding_service import ReviewerCodingError, require_reviewing_session
from app.services.social_autopsy_analysis_service import SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.user_note_service import get_active_note, save_note
from app.services.workflow.state_store import get_submission_workflow_state
from app.utils import va_get_form_type_code_for_form

bp = Blueprint("va_case_api", __name__)

#: ``mode`` query value -> the web ``action`` that picks the role's categories.
_ACTION_BY_MODE = {"coding": "vacode", "reviewing": "vareview"}
#: The open-session ``actiontype`` of each mode (a workspace is a resume of
#: the held allocation); it is what makes a category's required form block.
_SESSION_ACTIONTYPE = {"coding": "varesumecoding", "reviewing": "varesumereviewing"}
_CODING_ROLES = frozenset({"coder", "coding_tester"})


@dataclass
class _Case:
    mode: str
    va_action: str
    submission: VaSubmissions
    project: object
    project_mode: str
    form_type_code: str
    active_version: object
    visible_category_codes: list[str]
    recode_active: bool = False


def _private(response):
    """``private, no-store``: PHI on a shared browser is never cached."""
    response.cache_control.private = True
    response.cache_control.no_store = True
    response.cache_control.max_age = 0
    return response


@dataclass
class _Session:
    mode: str
    recode_active: bool


def _authorize_session(va_sid: str):
    """The ``_Session`` the caller holds on this case, or an error response.

    The cheap half of ``_authorize``: mode, role and the open allocation
    (coding: ``require_coding_session`` for the current episode; reviewing:
    REVIEW access plus the caller's own reviewing allocation). Nothing of the
    payload is read.
    """
    mode = request.args.get("mode")
    recode_active = False
    if mode not in _ACTION_BY_MODE:
        return api_error("mode must be coding or reviewing.", "invalid_request", 400)
    roles = effective_roles(current_user)
    try:
        if mode == "coding":
            if not roles & _CODING_ROLES:
                return api_error("Coder access is required.", "forbidden", 403)
            recode_active = get_active_recode_episode(va_sid) is not None
            require_coding_session(
                current_user, va_sid, derive_actiontype(va_sid, recode_active=recode_active)
            )
        else:
            if "reviewer" not in roles:
                return api_error("Reviewer access is required.", "forbidden", 403)
            require_reviewing_session(current_user, va_sid)
    except CoderCodingError as exc:
        return api_error(exc.message, exc.code, exc.status_code)
    except ReviewerCodingError as exc:
        return api_error(exc.message, exc.code, exc.status_code)
    return _Session(mode, recode_active)


def _authorize(va_sid: str):
    """The ``_Case`` the caller may open, or an ``(error response)`` tuple.

    Nothing of the payload is read before the allocation and scope checks
    pass; the visible-category computation below renders every category.
    """
    session = _authorize_session(va_sid)
    if not isinstance(session, _Session):
        return session
    mode, recode_active = session.mode, session.recode_active
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        return api_error("Submission not found.", "not_found", 404)
    project = get_project_for_submission(va_sid)
    active_version = get_active_payload_version(va_sid)
    return _Case(
        mode=mode,
        va_action=_ACTION_BY_MODE[mode],
        submission=submission,
        project=project,
        project_mode=get_project_mode(project),
        form_type_code=va_get_form_type_code_for_form(submission.va_form_id),
        active_version=active_version,
        visible_category_codes=get_visible_category_codes(
            active_version.payload_data if active_version else None, submission.va_form_id
        ),
        recode_active=recode_active,
    )


def _conditions(text) -> list[str]:
    return text.split(" | ") if text else []


def _iso(moment):
    """ISO 8601 with an explicit offset. The columns are naive and written in
    UTC (the web's ``user_timezone`` filter reads them the same way), so a
    client must not take them for local time."""
    if not moment:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


def _initial_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_iniassess_id),
        "immediate_cod": row.va_immediate_cod,
        "antecedent_cod": row.va_antecedent_cod,
        "other_conditions": _conditions(row.va_other_conditions),
        "created_at": _iso(row.va_iniassess_createdat),
    }


def _coder_final_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_finassess_id),
        "conclusive_cod": row.va_conclusive_cod,
        "immediate_cod": row.va_immediate_cod,
        "other_conditions": _conditions(row.va_other_conditions),
        "remark": row.va_finassess_remark,
        "created_at": _iso(row.va_finassess_createdat),
    }


def _reviewer_initial_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_riniassess_id),
        "immediate_cod": row.va_immediate_cod,
        "antecedent_cod": row.va_antecedent_cod,
        "other_conditions": _conditions(row.va_other_conditions),
        "created_at": _iso(row.va_riniassess_createdat),
    }


def _reviewer_final_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.va_rfinassess_id),
        "conclusive_cod": row.va_conclusive_cod,
        "immediate_cod": row.va_immediate_cod,
        "other_conditions": _conditions(row.va_other_conditions),
        "remark": row.va_rfinassess_remark,
        "created_at": _iso(row.va_rfinassess_createdat),
    }


def _not_codeable_json(row) -> dict | None:
    if row is None:
        return None
    return {
        "reason": row.va_creview_reason,
        "other": row.va_creview_other,
        "created_at": _iso(row.va_creview_createdat),
    }


def _narrative_qa_json(case: _Case, va_sid: str, user_id) -> dict | None:
    """The NQA form and the caller's own answers on the current payload, or
    ``None`` when the project has Narrative QA off (the save then 400s).

    A cannot-grade save stores zeros; they are returned as stored."""
    if not (case.project and case.project.narrative_qa_enabled):
        return None
    row = get_current_payload_narrative_assessment(va_sid, user_id)
    saved = None
    if row is not None:
        saved = {
            "cannot_grade": bool(row.va_nqa_cannot_grade),
            "values": {
                field["key"]: getattr(row, f"va_nqa_{field['key']}") for field in NARRATIVE_QA_FIELDS
            },
            "score": row.va_nqa_score,
            "rating": row.rating,
        }
    return {"fields": NARRATIVE_QA_FIELDS, "max_score": NARRATIVE_QA_MAX_SCORE, "saved": saved}


def _social_autopsy_json(case: _Case, va_sid: str, user_id) -> dict | None:
    """The SA questions and the caller's own answers on the current payload,
    or ``None`` when this role's SA switch is off (the save then 403s)."""
    if not social_autopsy_enabled(case.project, case.va_action):
        return None
    row = get_current_payload_social_autopsy_analysis(va_sid, user_id)
    saved = None
    if row is not None:
        # One SELECT for the row's options; sorted as the save normalizes them.
        pairs = sorted((option.delay_level, option.option_code) for option in row.selected_options)
        saved = {
            "selected_options": [
                {"delay_level": delay_level, "option_code": option_code}
                for delay_level, option_code in pairs
            ],
            "remark": row.va_saa_remark,
        }
    return {"questions": SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS, "saved": saved}


@bp.get("/<va_sid>/workspace")
@role_required("coder", "coding_tester", "reviewer")
def workspace(va_sid):
    """The workspace shell for ``?mode=coding|reviewing``.

    200 ``{case, categories, default_category, step, blocked_by,
    assessments, smartva, other_conditions_options, narrative_qa,
    social_autopsy}``; ``step`` is ``initial | final | done``.
    ``case.icd_classification`` (``icd10 | icd11``) names the coding search
    to call. ``narrative_qa`` / ``social_autopsy`` are ``None`` when the
    project's switch for this role is off, else the form definition plus the
    caller's own ``saved`` answers on the current payload (or ``None``).
    Errors ``{error, code}``: 400 ``invalid_request`` (mode), 403 ``forbidden`` / ``no_allocation``, 404
    ``not_found``.
    """
    case = _authorize(va_sid)
    if not isinstance(case, _Case):
        return case
    uid = current_user.user_id
    category_service = get_category_rendering_service()
    nav = category_service.get_category_nav(
        case.form_type_code, case.va_action, case.visible_category_codes
    )
    artifacts = get_case_artifacts(
        va_sid=va_sid,
        va_partial="vacodassessment",
        va_action=case.va_action,
        va_actiontype=_SESSION_ACTIONTYPE[case.mode],
        project=case.project,
        user_id=uid,
        own_reviewer_final=True,
    )
    masked = is_masked(case.project_mode)
    # The authoritative record carries the coder final it stands on (or
    # supersedes); one primary-key read, usually already in the session.
    authoritative = artifacts.va_final_assess
    coder_final = (
        db.session.get(VaFinalAssessments, authoritative.coder_final_assessment_id)
        if authoritative is not None and authoritative.coder_final_assessment_id
        else None
    )
    assessments = {
        "initial": None,
        "initial_prefill": None,
        "final": None,
        "not_codeable": None,
        "coder_initial": None,
        "reviewer_initial": None,
        "reviewer_final": None,
    }
    options = None
    if case.mode == "coding":
        prefill = get_step1_prefill(
            va_sid, uid, "vacode", recode_resume=True, recode_active=case.recode_active
        )
        own = prefill if prefill is not None and prefill.va_iniassess_status == VaStatuses.active else None
        assessments["initial"] = _initial_json(own)
        assessments["initial_prefill"] = _initial_json(prefill)
        step = coding_step(
            masked=masked, has_initial=own is not None, has_not_codeable=bool(artifacts.vaerrexists)
        )
        options = other_conditions_choices(case.active_version.payload_data if case.active_version else None)
        # The web's active coding panel shows neither before Step 2: another
        # coder's authoritative final would unblind a masked Step 1, and a
        # not-codeable review counts only as the caller's own.
        if step == "final":
            assessments["final"] = _coder_final_json(coder_final)
        if artifacts.va_coder_review is not None and artifacts.va_coder_review.va_creview_by == uid:
            assessments["not_codeable"] = _not_codeable_json(artifacts.va_coder_review)
    else:
        # The reviewer sees the coder's Step 1, final and not-codeable review
        # as read-only reference; the reviewer rows are their own.
        assessments["final"] = _coder_final_json(coder_final)
        assessments["not_codeable"] = _not_codeable_json(artifacts.va_coder_review)
        assessments["coder_initial"] = _initial_json(artifacts.va_initial_assess)
        assessments["reviewer_initial"] = _reviewer_initial_json(artifacts.va_reviewer_initial_assess)
        assessments["reviewer_final"] = _reviewer_final_json(artifacts.va_reviewer_final_assess)
        step = reviewing_step(
            masked=masked,
            has_initial=artifacts.va_reviewer_initial_assess is not None,
            has_final=artifacts.va_reviewer_final_assess is not None,
        )
    # SmartVA completes asynchronously, so it is read live, and a masked
    # project keeps it from Step 1 as the web does: shown once the caller
    # has their own Step 1.
    has_initial = (
        assessments["initial"] is not None
        if case.mode == "coding"
        else artifacts.va_reviewer_initial_assess is not None
    )
    smartva = None
    if not masked or has_initial:
        smartva = smartva_summary(get_active_smartva(va_sid))
    body = {
        "case": {
            "va_sid": va_sid,
            "instance_name": case.submission.va_uniqueid_masked,
            "form_type_code": case.form_type_code,
            "project_mode": case.project_mode,
            # get_icd_classification_for_submission's answer from the project
            # already loaded (same submission -> form -> project path).
            "icd_classification": (
                case.project.icd_classification
                if case.project and case.project.icd_classification
                else DEFAULT_ICD_CLASSIFICATION
            ),
            "workflow_state": get_submission_workflow_state(va_sid),
            "narrative_qa_enabled": bool(case.project and case.project.narrative_qa_enabled),
            "social_autopsy_enabled": social_autopsy_enabled(case.project, case.va_action),
        },
        "categories": [
            {
                "code": item.category_code,
                "label": item.display_label,
                "nav_label": item.nav_label,
                "render_mode": item.render_mode,
            }
            for item in nav
        ],
        "default_category": category_service.get_default_category_code(
            case.form_type_code, case.va_action, case.visible_category_codes
        ),
        "step": step,
        "blocked_by": final_blockers(
            va_sid=va_sid,
            va_action=case.va_action,
            user_id=uid,
            project=case.project,
            form_type_code=case.form_type_code,
            visible_category_codes=case.visible_category_codes,
        ),
        "assessments": assessments,
        "smartva": smartva,
        "other_conditions_options": options,
        "narrative_qa": _narrative_qa_json(case, va_sid, uid),
        "social_autopsy": _social_autopsy_json(case, va_sid, uid),
    }
    return _private(jsonify(body))


def _subcategories(data, labels, render_modes, flip_labels, info_labels) -> list[dict]:
    """Ordered ``[{code, label, render_mode, items}]``; never label-keyed
    dicts, which Flask's JSON provider would sort."""
    return [
        {
            "code": code,
            "label": labels.get(code, code),
            "render_mode": render_modes.get(code, "default"),
            "items": [
                {
                    "label": label,
                    "value": value,
                    "flip": label in flip_labels,
                    "info": label in info_labels,
                }
                for label, value in section.items()
            ],
        }
        for code, section in data.items()
    ]


@bp.get("/<va_sid>/categories/<code>")
@role_required("coder", "coding_tester", "reviewer")
def category(va_sid, code):
    """One category's data for ``?mode=coding|reviewing``.

    200 ``{code, label, render_mode, summary_items, subcategories, blocked_by}``;
    attachment values are ``/api/v1/attachments`` URLs (cookie or
    bearer). A category the role does not see is 404 ``not_found``, as one
    that does not exist. Errors as ``workspace``.
    """
    case = _authorize(va_sid)
    if not isinstance(case, _Case):
        return case
    category_service = get_category_rendering_service()
    if not category_service.is_category_enabled(
        case.form_type_code, case.va_action, case.visible_category_codes, code
    ):
        return api_error("Category not found.", "not_found", 404)
    config = category_service.get_category_config(case.form_type_code, case.va_action, code)
    mapping = get_mapping_service()
    ftc = case.form_type_code
    section = get_section_data(
        va_submission=case.submission,
        active_version=case.active_version,
        form_type_code=ftc,
        va_action=case.va_action,
        va_partial=code,
        category_config=config,
        visible_category_codes=case.visible_category_codes,
        user=current_user,
    )
    flip, info = mapping.get_flip_labels(ftc), mapping.get_info_labels(ftc)
    subcategories = _subcategories(
        section["va_processedcategorydata"],
        mapping.get_subcategory_labels(ftc, code),
        mapping.get_subcategory_render_modes(ftc, code),
        flip,
        info,
    )
    if config.render_mode == "workflow_panel":
        subcategories += _subcategories(
            section["cod_attachments_data"],
            section["cod_attachments_labels"],
            section["cod_attachments_render_modes"],
            flip,
            info,
        )
        subcategories += _subcategories(
            section["cod_health_history_data"],
            section["cod_health_history_labels"],
            mapping.get_subcategory_render_modes(ftc, "vahealthhistorydetails"),
            flip,
            info,
        )
    block = category_block_code(
        va_sid, code, case.va_action, _SESSION_ACTIONTYPE[case.mode], case.project, current_user.user_id
    )
    body = {
        "code": code,
        "label": config.display_label,
        "render_mode": config.render_mode,
        "summary_items": section["summary_items"],
        "subcategories": subcategories,
        "blocked_by": [block] if block else [],
    }
    # Unlike the web partial (max-age 300 for data categories), never stored:
    # PHI on a shared browser.
    return _private(jsonify(body))


#: Body cap by ``Content-Length`` and the text cap in characters of a note.
_NOTE_BODY_CAP = 64 * 1024
_NOTE_MAX_CHARS = 20_000


def _note_json(va_sid: str):
    note = get_active_note(current_user.user_id, va_sid)
    return _private(jsonify({
        "va_sid": va_sid,
        "content": note.note_content if note else None,
        "updated_at": _iso(note.note_updated_at) if note else None,
    }))


@bp.get("/<va_sid>/note")
@role_required("coder", "coding_tester", "reviewer")
def get_note(va_sid):
    """The caller's private note on the case, for ``?mode=coding|reviewing``.

    200 ``{va_sid, content, updated_at}``, both null when there is none. Own
    allocation only (as ``workspace``; the web also allows a note on its view
    page). One note per user per case, shared by both modes. Errors as
    ``workspace``.
    """
    session = _authorize_session(va_sid)
    if not isinstance(session, _Session):
        return session
    return _note_json(va_sid)


@bp.put("/<va_sid>/note")
@role_required("coder", "coding_tester", "reviewer")
def put_note(va_sid):
    """Save the caller's private note ``{"content": text}``; replies as ``get_note``.

    400 ``invalid_request`` for a body that is not an object with text
    ``content``, for empty or whitespace-only content or one holding NUL; 413 ``too_large``
    over 64 KB or without a ``Content-Length`` (chunked); 422 ``invalid_request`` over 20,000 characters. Else as
    ``workspace``.
    """
    # Keyed on the path only, so no lookup runs before the size is known;
    # CSRF has already built the request stream without a limit, so only
    # Content-Length can enforce it. A chunked body has none and is refused
    # the same way, so it is never buffered.
    if request.content_length is None or request.content_length > _NOTE_BODY_CAP:
        return api_error("The note is too large.", "too_large", 413)
    session = _authorize_session(va_sid)
    if not isinstance(session, _Session):
        return session
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        body = None
    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, str) or not content.strip():
        return api_error("content must be non-empty text.", "invalid_request", 400)
    if "\x00" in content:  # PostgreSQL text cannot hold NUL
        return api_error("content must not contain NUL characters.", "invalid_request", 400)
    if len(content) > _NOTE_MAX_CHARS:
        return api_error(f"A note is at most {_NOTE_MAX_CHARS} characters.", "invalid_request", 422)
    save_note(current_user.user_id, va_sid, content)
    return _note_json(va_sid)
