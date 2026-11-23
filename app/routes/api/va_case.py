"""Case workspace content — /api/v1/va/<sid>/workspace, .../categories/<code>, .../note

One call for the workspace shell, one per category, for any client (cookie or
bearer). Authorization comes first and is the one the COD writes use: coding
needs the caller's active coding allocation (``require_coding_session``),
reviewing REVIEW access plus their own active reviewing allocation. The
content itself is ``case_content_service``, which the web partials render
from too. ``mode=view`` is the web's ``/coding/area/<sid>``: authorized by
``Action.VIEW`` alone (no allocation), the viewer's categories and the saved
assessments as read-only reference once coding is finished, never an
editable block. The private
note takes the allocation check without rendering any category, so it
refuses ``mode=view``.
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import (
    VaForms,
    VaProjectMaster,
    VaSubmissions,
)
from app.routes.api.request_helpers import error as api_error
from app.services import training_scope
from app.services import web_intake_service as intake_svc
from app.services.authz import Action, AuthzError, effective_roles, require
from app.services.case_content_service import (
    category_block_code,
    get_section_data,
    payload_for_viewer,
)
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.cod_entry_mode import project_mode as get_project_mode
from app.services.coder_cod_service import (
    CoderCodingError,
    derive_actiontype,
    require_coding_session,
)
from app.services.cod_certificate_service import certificate_context, record_certificate_view
from app.services.coder_workflow_service import get_active_coding_allocation
from app.services.coding_service import _count_attachments_per_category
from app.services.demo_project_service import is_demo_training_project
from app.services.field_mapping_service import get_mapping_service
from app.services.final_cod_authority_service import get_active_recode_episode
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    require_reviewing_session,
)
from app.services.submission_payload_version_service import (
    get_active_payload_version,
    joined_payload,
)
from app.services.user_note_service import get_active_note, save_note
from app.services.viewer_pii_service import should_redact_pii
from app.services.workflow.definition import (
    CODING_BUCKET_CODED,
    CODING_BUCKET_NOT_CODEABLE,
    coding_bucket,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workspace_service import SESSION_ACTIONTYPE as _SESSION_ACTIONTYPE
from app.services.workspace_service import _iso, build_workspace
from app.services.workspace_service import (  # noqa: F401 - re-export: scripts/export_offline_va_display_golden.py
    _category_counts,
)
from app.utils import va_get_form_type_code_for_form
from app.utils.va_render.va_render_05_mapchoicevalue import va_render_mapchoicevalue
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel

bp = Blueprint("va_case_api", __name__)

#: ``mode`` query value -> the web ``action`` that picks the role's categories.
_ACTION_BY_MODE = {"coding": "vacode", "reviewing": "vareview", "view": "vaarea"}
_SESSION_MODES = ("coding", "reviewing")
_CODING_ROLES = frozenset({"coder", "coding_tester"})


@dataclass
class _Case:
    mode: str
    va_action: str
    submission: VaSubmissions
    project: object
    project_code: str | None
    site_code: str | None
    is_demo_project: bool
    project_mode: str
    form_type_code: str
    active_version: object
    visible_category_codes: list[str]
    recode_active: bool = False
    intake_only: bool = False

    @property
    def project_id(self) -> str | None:
        """The case's project, for per-project PII (digitva-ssg7.3); None redacts."""
        return getattr(self.project, "project_id", None)


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
    #: ``mode=view`` opened by the intake gate alone (the submitter or a
    #: supervisor of the case, no ``Action.VIEW``): answers only, never the
    #: coders' work or the workflow history.
    intake_only: bool = False


def _authorize_session(va_sid: str):
    """The ``_Session`` the caller holds on this case, or an error response.

    The cheap half of ``_authorize``: mode, role and the open allocation
    (coding: ``require_coding_session`` for the current episode; reviewing:
    REVIEW access plus the caller's own reviewing allocation). Nothing of the
    payload is read.
    """
    mode = request.args.get("mode")
    recode_active = False
    if mode not in _SESSION_MODES:
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


def _authorize_view(va_sid: str):
    """``_Session`` for ``mode=view`` (``Action.VIEW``, no allocation), or an
    error response: 404 for a missing case, else 403. Without VIEW, the
    interviewer whose draft became the submission or a supervisor of its
    case may still read the answers (``may_read_submitted_answers``,
    docs/policy/interview-revisions.md): an ``intake_only`` session."""
    try:
        require(current_user, Action.VIEW, va_sid)
    except AuthzError as exc:
        training_scope.resolve("interview")  # a training case reads only with ?training=1
        if intake_svc.may_read_submitted_answers(current_user, va_sid):
            return _Session("view", False, intake_only=True)
        return api_error(exc.message, status_code=exc.status_code)
    return _Session("view", False)


def _authorize(va_sid: str):
    """The ``_Case`` the caller may open, or an ``(error response)`` tuple.

    Nothing of the payload is read before the allocation (``mode=view``:
    VIEW) and scope checks pass; the visible-category computation below
    renders every category.
    """
    if request.args.get("mode") == "view":
        session = _authorize_view(va_sid)
    else:
        session = _authorize_session(va_sid)
    if not isinstance(session, _Session):
        return session
    mode, recode_active = session.mode, session.recode_active
    submission = db.session.get(VaSubmissions, va_sid)
    if submission is None:
        return api_error("Submission not found.", "not_found", 404)
    form = db.session.get(VaForms, submission.va_form_id) if submission.va_form_id else None
    project = db.session.get(VaProjectMaster, form.project_id) if form else None
    active_version = get_active_payload_version(va_sid)
    return _Case(
        mode=mode,
        va_action=_ACTION_BY_MODE[mode],
        submission=submission,
        project=project,
        project_code=(
            (project.project_code if project and project.project_code else None)
            or (form.project_id if form else None)
        ),
        site_code=form.site_id if form else None,
        is_demo_project=is_demo_training_project(project),
        project_mode=get_project_mode(project),
        form_type_code=va_get_form_type_code_for_form(submission.va_form_id),
        active_version=active_version,
        visible_category_codes=get_visible_category_codes(
            joined_payload(active_version) if active_version else None, submission.va_form_id
        ),
        recode_active=recode_active,
        intake_only=session.intake_only,
    )


def _survey_location(case: _Case, nav, viewer_payload) -> dict:
    """Survey district/state labels for the case header, as the category tables show them.

    ``viewer_payload`` is the PII-redacted payload (``payload_for_viewer``,
    computed once per request); a field counts only if a category the viewer
    can open (``nav``) lists it, so the header never shows what the tables omit.
    """
    datalevel = va_get_render_datalevel(case.va_action, case.form_type_code, case.visible_category_codes)
    shown = {
        field
        for item in nav
        for fields in datalevel.get(item.category_code, {}).values()
        for field in fields
    }
    choices = get_mapping_service().get_choices(case.form_type_code)
    out = {}
    for field in ("survey_district", "survey_state"):
        value = (viewer_payload or {}).get(field) if field in shown else None
        # The payload holds a code; the table shows its choice label, so does the header.
        label = None if value is None else va_render_mapchoicevalue(field, value, choices)
        out[field] = (str(label).strip() or None) if label is not None else None
    return out


def _may_see_cod_reference(va_sid: str, workflow_state: str | None, user_id) -> bool:
    """Whether a ``mode=view`` caller may see the COD reference and SmartVA.

    Only once coding is finished (``coded`` / ``not_codeable`` bucket), and
    never to a caller holding a coding or reviewing allocation on this case:
    a view must not unblind a coder or reviewer who is still working it.
    """
    if coding_bucket(workflow_state) not in (CODING_BUCKET_CODED, CODING_BUCKET_NOT_CODEABLE):
        return False
    held = {
        get_active_coding_allocation(user_id, training=side) for side in (False, True)
    } | {get_active_reviewing_allocation(user_id, training=side) for side in (False, True)}
    return va_sid not in held




@bp.get("/<va_sid>/workspace")
# interviewer and interview_supervisor reach only mode=view's intake gate.
@role_required(
    "coder", "coding_tester", "reviewer", "collaborator", "collaborator_pii", "admin",
    "interviewer", "interview_supervisor",
)
def workspace(va_sid):
    """The workspace shell for ``?mode=coding|reviewing|view``.

    200 ``{case, categories, default_category, step, blocked_by,
    assessments, smartva, smartva_status, smartva_can_run,
    other_conditions_options, narrative_qa, social_autopsy, doris,
    codingTimelineV1}``; ``codingTimelineV1`` is additive and contains the
    caller-visible coder's bounded allocation, DORIS and assessment times;
    allocation is the durable start marker, not an editor-open timestamp.
    ``step`` is ``initial | final | done``, or
    ``view`` for a read-only view: ``blocked_by`` is empty, ``doris``,
    ``narrative_qa``, ``social_autopsy``, ``other_conditions_options`` and
    ``assessments.initial|initial_prefill`` are ``None`` (``case``'s two
    switches false), ``final`` is the coder final the authoritative record
    stands on, ``reviewer_final`` the latest active reviewer final of anyone,
    ``coder_initial`` the display initial; those three, ``not_codeable`` and
    SmartVA are ``None`` unless coding is finished (``coded`` /
    ``not_codeable`` bucket) and the caller holds no coding or reviewing
    allocation on the case.
    ``case.icd_classification`` (``icd10 | icd11``) names the coding search
    to call. ``narrative_qa`` / ``social_autopsy`` are ``None`` when the
    project's switch for this role is off, else the form definition plus the
    caller's own ``saved`` answers on the current payload (or ``None``).
    ``doris`` is ``None`` outside DORIS projects, else the editor's seed
    (``doris_context_service.workspace_doris``).
    Errors ``{error, code}``: 400 ``invalid_request`` (mode), 403 ``forbidden`` / ``no_allocation``, 404
    ``not_found``.
    """
    case = _authorize(va_sid)
    if not isinstance(case, _Case):
        return case
    body, workflow_state = build_workspace(
        case,
        va_sid,
        current_user,
        redact_pii=should_redact_pii,
        count_attachments_per_category=_count_attachments_per_category,
        viewer_payload_of=payload_for_viewer,
        survey_location=_survey_location,
        may_see_cod_reference=_may_see_cod_reference,
        read_state=get_submission_workflow_state,
    )
    body["case"]["workflow_state"] = workflow_state
    return _private(jsonify(body))


def _subcategories(
    data, labels, render_modes, flip_labels, info_labels, *, source_category: str
) -> list[dict]:
    """Ordered subcategories with their source category; never label-keyed
    dicts, which Flask's JSON provider would sort."""
    return [
        {
            "code": code,
            "label": labels.get(code, code),
            "source_category": source_category,
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


def category_subcategories(section: dict, config, form_type_code: str, code: str) -> list[dict]:
    """A category's ordered subcategories from its ``get_section_data`` result.

    The workflow panel appends the narrative and documents, then the health history,
    each tagged with its source category. Pure over *section*, so the offline
    display golden calls it with a locally built section.
    """
    mapping = get_mapping_service()
    ftc = form_type_code
    flip, info = mapping.get_flip_labels(ftc), mapping.get_info_labels(ftc)
    subcategories = _subcategories(
        section["va_processedcategorydata"],
        mapping.get_subcategory_labels(ftc, code),
        mapping.get_subcategory_render_modes(ftc, code),
        flip,
        info,
        source_category=code,
    )
    if config.render_mode == "workflow_panel":
        subcategories += _subcategories(
            section["cod_attachments_data"],
            section["cod_attachments_labels"],
            section["cod_attachments_render_modes"],
            flip,
            info,
            source_category="vanarrationanddocuments",
        )
        subcategories += _subcategories(
            section["cod_health_history_data"],
            section["cod_health_history_labels"],
            mapping.get_subcategory_render_modes(ftc, "vahealthhistorydetails"),
            flip,
            info,
            source_category="vahealthhistorydetails",
        )
    return subcategories


@bp.get("/<va_sid>/categories/<code>")
@role_required(
    "coder", "coding_tester", "reviewer", "collaborator", "collaborator_pii", "admin",
    "interviewer", "interview_supervisor",
)
def category(va_sid, code):
    """One category's data for ``?mode=coding|reviewing|view``.

    200 ``{code, label, render_mode, summary_items, subcategories, blocked_by}``;
    attachment values are ``/api/v1/attachments`` URLs (cookie or
    bearer). A category the role does not see is 404 ``not_found``, as one
    that does not exist. ``mode=view`` never blocks and, for a caller who
    sees no personal data, serves the redacted section. Errors as ``workspace``.
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
        project_id=case.project_id,
    )
    subcategories = category_subcategories(section, config, ftc, code)
    block = (
        None
        if case.mode == "view"
        else category_block_code(
            va_sid, code, case.va_action, _SESSION_ACTIONTYPE[case.mode], case.project, current_user.user_id
        )
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
        return api_error("The note is too large.", "payload_too_large", 413)
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


@bp.get("/<va_sid>/certificate")
@role_required("coder", "coding_tester", "reviewer", "collaborator", "collaborator_pii", "admin")
def certificate(va_sid):
    """The WHO-form cause-of-death certificate data of a coded organization case.

    200 ``certificate_context`` as JSON (PII already redacted by the viewer
    gate; the phone renders the PDF from it). 404 ``not_found`` for every
    unavailable case, scope included, so the reason is not revealed. Policy:
    docs/policy/cod-certificate-export.md. One audit row per served response.
    """
    try:
        require(current_user, Action.VIEW, va_sid)
    except AuthzError:
        return api_error("Certificate not available.", "not_found", 404)
    context = certificate_context(current_user, va_sid)
    if context is None:
        return api_error("Certificate not available.", "not_found", 404)
    record_certificate_view(current_user, va_sid)
    context["coded_at"] = _iso(context["coded_at"])
    context["generated_at"] = _iso(context["generated_at"])
    response = jsonify(context)
    response.cache_control.private = True
    response.cache_control.no_store = True
    return response
