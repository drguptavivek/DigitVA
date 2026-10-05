import copy
import json
import logging
import uuid

import sqlalchemy as sa
from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app import db
from app.decorators import role_required, va_validate_permissions
from app.forms import (
    VaCoderReviewForm,
    VaDataManagerReviewForm,
    VaFinalAssessmentForm,
    VaInitialAssessmentForm,
    VaReviewerReviewForm,
    VaUsernoteForm,
)
from app.models import (
    VaDataManagerReview,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
)
from app.services import attachment_service
from app.services.authz import Action, AuthzError, require
from app.services.case_content_service import (
    get_case_artifacts,
    get_section_data,
    get_step1_prefill,
    nqa_blocks_final,
    response_contains_user_specific_artifacts,
)
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.cod_entry_mode import is_doris as _is_doris
from app.services.cod_entry_mode import is_masked as _is_masked
from app.services.cod_entry_mode import project_mode as _project_mode
from app.services.cod_entry_mode import (
    smartva_icd11_alternatives as _smartva_icd11_alternatives,
)
from app.services.coder_cod_service import (
    STEP1_REQUIRED_MESSAGE,
    TESTER_SAVED_MESSAGE,
    CoderCodingError,
    other_conditions_choices,
    submit_coder_final_cod,
    submit_coder_initial_cod,
    submit_coder_not_codeable,
)
from app.services.coding_service import get_project_for_submission as _get_project_for_submission
from app.services.doris_prefill import doris_prefill_from_payload
from app.services.field_mapping_service import get_mapping_service
from app.services.final_cod_authority_service import (
    get_authoritative_final_assessment,
)
from app.services.odk_review_service import sync_not_codeable_review_state
from app.services.payload_bound_coding_artifact_service import (
    deactivate_other_active_reviewer_reviews,
    get_submission_with_current_payload,
)
from app.services.social_autopsy_analysis_service import SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.user_note_service import get_active_note, save_note
from app.services.viewer_pii_service import should_redact_pii
from app.services.workflow.definition import (
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_SCREENING_PENDING,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    sync_submission_workflow_from_legacy_records,
)
from app.services.workflow.transitions import (
    data_manager_actor,
    mark_data_manager_not_codeable,
)
from app.utils import (
    va_get_form_type_code_for_form,
    va_permission_abortwithflash,
    va_permission_ensureallocation,
)

log = logging.getLogger(__name__)
va_form = Blueprint("va_form", __name__)


def _apply_partial_cache_policy(response, va_partial: str, va_action: str):
    """Apply HTTP cache headers for rendered form partials."""
    response.cache_control.private = True
    if response_contains_user_specific_artifacts(va_partial, va_action):
        response.cache_control.no_store = True
        response.cache_control.max_age = 0
    else:
        response.cache_control.max_age = 300  # 5 minutes — PHI data
    return response


def _nqa_blocks_final(va_sid, va_action, project) -> bool:
    """True when this coder must save the NQA before the final COD form."""
    return nqa_blocks_final(va_sid, va_action, project, current_user.user_id)


_DORIS_ENVELOPE_FIELDS = (
    "doris_certificate",
    "doris_result",
    "codedit_result",
    "doris_process_token",
    "doris_result_digest",
)


def _masked_doris_step2_context(step1, smartva) -> dict:
    """Template data for the masked DORIS Step 2 picker host.

    The picker's API URLs default in the template from ``va_sid``.
    """
    return {
        "smartva_icd11_alternatives": _smartva_icd11_alternatives(smartva),
        "step1_doris_certificate": step1.doris_certificate if step1 else None,
        "step1_doris_processing": (
            {"doris": step1.doris_result, "codedit": step1.codedit_result}
            if step1 and step1.doris_result is not None
            else None
        ),
    }


def _masked_reviewer_doris_context(va_sid, reviewer_initial, smartva):
    """Seed row and template data for the masked DORIS reviewer panel.

    Returns ``(doris_source, context)``. The reviewer's Step 1 editor starts
    from their own saved certificate, else from the certificate of the
    coder's Step 1 behind the authoritative coder final (the template
    deep-copies it, so the coder's rows never change), else ``None`` for the
    admin defaults. A saved reviewer Step 1 reopens display-only: no process
    token is minted on GET, so saving a changed Step 1 still needs Process.
    """
    context = _masked_doris_step2_context(reviewer_initial, smartva)
    if reviewer_initial is not None and reviewer_initial.doris_certificate:
        if reviewer_initial.doris_result is not None:
            context["doris_initial_processing"] = {
                "certificate": reviewer_initial.doris_certificate,
                "doris": reviewer_initial.doris_result,
                "codedit": reviewer_initial.codedit_result,
                "final_choice": reviewer_initial.va_antecedent_cod or "",
            }
        return reviewer_initial, context
    coder_final = get_authoritative_final_assessment(va_sid)
    coder_step1 = (
        db.session.get(VaInitialAssessments, coder_final.source_initial_assessment_id)
        if coder_final is not None and coder_final.source_initial_assessment_id
        else None
    )
    return coder_step1, context


_DORIS_CONFLICT_CODES = {
    "DORIS_CERTIFICATE_CHANGED",
    "DORIS_PROCESS_MISMATCH",
    "DORIS_PROCESS_EXPIRED",
}


def _coder_error_response(exc: CoderCodingError):
    """The web's JSON refusal for a ``CoderCodingError``.

    A DORIS conflict keeps its ``schema_version`` body (the editor reads
    ``processing`` from it); every other refusal is ``{error}``.
    """
    if exc.code in _DORIS_CONFLICT_CODES:
        return _doris_conflict(exc.code, exc.message, exc.processing)
    return jsonify(error=exc.message), exc.status_code


def _doris_form_kwargs() -> dict:
    """The posted DORIS envelopes as keyword arguments for the coder service.

    Malformed JSON is passed on as ``doris_input_error``, which the service
    refuses (422) where it would verify the proof.
    """
    raw_revision = request.form.get("doris_client_revision") or 0
    try:
        revision = int(raw_revision)
    except ValueError:
        revision = raw_revision  # the processor refuses it with a 422
    kwargs = {
        "doris_process_token": request.form.get("doris_process_token") or "",
        "doris_result_digest": request.form.get("doris_result_digest") or "",
        "doris_client_revision": revision,
    }
    try:
        kwargs["doris_certificate"] = _json_form_value("doris_certificate")
        kwargs["doris_result"] = _json_form_value("doris_result")
        kwargs["codedit_result"] = _json_form_value("codedit_result")
    except ValueError as exc:
        kwargs["doris_input_error"] = str(exc)
    return kwargs


def _json_form_value(name: str):
    raw = request.form.get(name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} must be valid JSON.") from exc


def _doris_initial(saved_certificate, submission, project_mode) -> tuple[dict, dict]:
    """``(initial certificate, prefill provenance)`` for a DORIS editor.

    A saved (or just-submitted) certificate is shown as it is, with no
    prefill markers. Otherwise a DORIS project's new certificate starts
    with the non-cause fields the interview answers
    (``doris_prefill_from_payload``, bead digitva-hln); these are interview
    facts, not SmartVA output, so masked Step 1 shows them too.
    """
    if saved_certificate is not None:
        certificate = copy.deepcopy(saved_certificate)
        if should_redact_pii(current_user) and isinstance(certificate, dict):
            # AdministrativeData holds the deceased's Sex, DateBirth,
            # DateDeath and age; a plain viewer keeps the cause chain only.
            certificate.pop("AdministrativeData", None)
        return certificate, {}
    if submission is None or not _is_doris(project_mode):
        return {}, {}
    if should_redact_pii(current_user):
        # The prefill is the deceased's Sex, DateBirth, DateDeath and age.
        return {}, {}
    version = get_active_payload_version(submission.va_sid)
    return doris_prefill_from_payload(version.payload_data if version else None)


def _doris_conflict(code: str, message: str, processing: dict | None = None):
    payload = {"schema_version": 1, "error": {"code": code, "message": message}}
    if processing is not None:
        payload["processing"] = processing
    return jsonify(payload), 409


DATA_MANAGER_TRIAGE_ALLOWED_STATES = {
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
}


def _data_manager_reason_label(reason_code: str) -> str:
    label_map = {
        "submission_incomplete": "Submission information is incomplete or unusable.",
        "source_data_mismatch": "Submission content does not match the expected deceased or source data.",
        "duplicate_submission": "This appears to be a duplicate submission.",
        "language_unreadable": "Narrative or key data cannot be understood for coding preparation.",
        "others": "Other issue reported by data manager.",
    }
    return label_map.get(reason_code, reason_code)


# Partials whose POST writes a coder-attributed record (Step 1, the final COD,
# coder Not Codeable). Each also requires the coder's active allocation below.
_CODING_WRITE_PARTIALS = frozenset({"vainitialasses", "vafinalasses", "vacoderreview"})

# The read-only renderings (validator ``_validate_read_only``) and the
# non-category partials they may load. Anything else under these actions,
# including a future non-category partial, is refused: fail closed.
_READ_ONLY_ACTIONS = frozenset({"vadata", "vaarea"})
_READ_ONLY_EXTRA_PARTIALS = frozenset({"workflow_history", "vausernote"})


def _require_partial_write(va_sid, va_partial, va_action, va_actiontype) -> None:
    """Authorize a writing partial by its own write action.

    The validator proves only the rendering the request names (``VIEW`` for
    ``vadata`` and ``vaarea``), so a partial that writes asks authz for its
    write action here: someone who may read a submission cannot triage, code,
    review or annotate it through the shared endpoint. Read partials need
    nothing more. Workflow checks (allocation, state) stay in each branch.
    Design: .tasks/digitva-0wc-design.md section 2.4.

    - ``vadmtriage``: TRIAGE, on GET as well, since the panel is the triage
      form and its GET reconciles the workflow state.
    - ``vainitialasses``, ``vafinalasses``, ``vacoderreview`` POST: CODE, or
      RECODE for ``varecode``; admin demo coding is its own path, as in
      ``_validate_vacode``.
    - ``vareviewform`` POST: REVIEW.
    - ``vausernote`` POST: a private note, saved only from the coding or
      reviewing page that offers the panel, then VIEW.
    """
    if va_partial == "vadmtriage":
        action = Action.TRIAGE
    elif request.method != "POST":
        return
    elif va_partial in _CODING_WRITE_PARTIALS:
        if va_actiontype == "vademo_start_coding" and current_user.is_admin():
            return
        action = Action.RECODE if va_actiontype == "varecode" else Action.CODE
    elif va_partial == "vareviewform":
        action = Action.REVIEW
    elif va_partial == "vausernote":
        if va_action not in {"vacode", "vareview"}:
            va_permission_abortwithflash("Notes are saved from a coding or review session.", 403)
        action = Action.VIEW
    else:
        return
    try:
        require(current_user, action, va_sid)
    except AuthzError as e:
        va_permission_abortwithflash(e.message, e.status_code)


@va_form.route("/<va_sid>/<va_partial>", methods=["GET", "POST"])
# Every grant role: the gate decides (authz.effective_roles) before
# va_validate_permissions turns away a malformed URL; which submission and
# action the user may open is its authz.require (digitva-5hmc).
@role_required(
    "admin", "coder", "coding_tester", "reviewer", "data_manager", "site_pi",
    "project_pi", "interviewer", "interview_supervisor", "collaborator",
    "collaborator_pii",
)
@va_validate_permissions()
def renderpartial(va_sid, va_partial):
    va_submission = db.session.get(VaSubmissions, va_sid)
    project = _get_project_for_submission(va_sid) if va_submission else None
    project_mode = _project_mode(project)
    if (
        request.method == "POST"
        and va_partial in {"vainitialasses", "vafinalasses"}
        and _is_doris(project_mode)
        and (request.content_length is None or request.content_length > 1_200_000)
    ):
        return jsonify(error="DORIS submission is too large."), 413
    va_action = request.values.get("action", "vacode")
    va_actiontype = request.values.get("actiontype", "")
    if va_partial == "vainitialasses" and not _is_masked(project_mode):
        va_partial = "vafinalasses"
    _require_partial_write(va_sid, va_partial, va_action, va_actiontype)
    _active_version = get_active_payload_version(va_sid) if va_submission else None
    va_payload_data = _active_version.payload_data if _active_version else None
    _form_type_code = va_get_form_type_code_for_form(
        va_submission.va_form_id if va_submission else None
    )
    visible_category_codes = get_visible_category_codes(
        va_payload_data,
        va_submission.va_form_id if va_submission else None,
    )
    category_service = get_category_rendering_service()
    if category_service.is_category_enabled(
        _form_type_code,
        va_action,
        visible_category_codes,
        va_partial,
    ):
        if va_partial == "vadmtriage":
            form = VaDataManagerReviewForm()
            active_dm_review = db.session.scalar(
                sa.select(VaDataManagerReview).where(
                    VaDataManagerReview.va_sid == va_sid,
                    VaDataManagerReview.va_dmreview_status == VaStatuses.active,
                )
            )
            smartva = db.session.scalar(
                sa.select(VaSmartvaResults).where(
                    (VaSmartvaResults.va_sid == va_sid)
                    & (VaSmartvaResults.va_smartva_status == VaStatuses.active)
                )
            )
            submission_workflow = db.session.scalar(
                sa.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == va_sid
                )
            )
            if smartva and submission_workflow == "smartva_pending":
                sync_submission_workflow_from_legacy_records(
                    va_sid,
                    reason="reconciled_from_active_smartva_result",
                    by_role="vasystem",
                )
                db.session.commit()
                submission_workflow = get_submission_workflow_state(va_sid)
            success_message = None

            if request.method == "POST":
                # TRIAGE was required for this submission by _require_partial_write.
                if submission_workflow not in DATA_MANAGER_TRIAGE_ALLOWED_STATES:
                    return render_template(
                        "va_formcategory_partials/category_data_manager_triage.html",
                        category_config=category_service.get_category_config(
                            _form_type_code,
                            va_action,
                            va_partial,
                        ),
                        va_action=va_action,
                        va_actiontype=va_actiontype,
                        va_sid=va_sid,
                        va_partial=va_partial,
                        form=form,
                        va_previouscategory=category_service.get_category_neighbours(
                            _form_type_code,
                            va_action,
                            visible_category_codes,
                            va_partial,
                        )[0],
                        va_nextcategory=category_service.get_category_neighbours(
                            _form_type_code,
                            va_action,
                            visible_category_codes,
                            va_partial,
                        )[1],
                        active_dm_review=active_dm_review,
                        submission_workflow_state=submission_workflow,
                        smartva=smartva,
                        form_error_messages=[
                            "This submission can only be flagged by a data manager before coder workflow begins."
                        ],
                    )
                if form.validate_on_submit():
                    other_reason = (form.va_dmreview_other.data or "").strip() or None
                    if active_dm_review:
                        active_dm_review.va_dmreview_reason = form.va_dmreview_reason.data
                        active_dm_review.va_dmreview_other = other_reason
                        audit_action = "data manager not codeable updated"
                        audit_operation = "u"
                        entity_id = active_dm_review.va_dmreview_id
                    else:
                        entity_id = uuid.uuid4()
                        active_dm_review = VaDataManagerReview(
                            va_dmreview_id=entity_id,
                            va_sid=va_sid,
                            va_dmreview_by=current_user.user_id,
                            va_dmreview_reason=form.va_dmreview_reason.data,
                            va_dmreview_other=other_reason,
                        )
                        db.session.add(active_dm_review)
                        audit_action = "submission flagged not codeable by data manager"
                        audit_operation = "c"
                    db.session.add(
                        VaSubmissionsAuditlog(
                            va_sid=va_sid,
                            va_audit_byrole="data_manager",
                            va_audit_by=current_user.user_id,
                            va_audit_operation=audit_operation,
                            va_audit_action=audit_action,
                            va_audit_entityid=entity_id,
                        )
                    )
                    mark_data_manager_not_codeable(
                        va_sid,
                        reason="data_manager_marked_not_codeable",
                        actor=data_manager_actor(current_user.user_id),
                    )
                    odk_sync_result = sync_not_codeable_review_state(
                        va_sid,
                        form.va_dmreview_reason.data,
                        other_reason,
                        actor_role="data_manager",
                    )
                    if odk_sync_result.success:
                        db.session.add(
                            VaSubmissionsAuditlog(
                                va_sid=va_sid,
                                va_audit_byrole="data_manager",
                                va_audit_by=current_user.user_id,
                                va_audit_operation="u",
                                va_audit_action=(
                                    "odk review state set to "
                                    f"{odk_sync_result.review_state}"
                                ),
                            )
                        )
                    else:
                        db.session.add(
                            VaSubmissionsAuditlog(
                                va_sid=va_sid,
                                va_audit_byrole="data_manager",
                                va_audit_by=current_user.user_id,
                                va_audit_operation="u",
                                va_audit_action="odk review state update failed",
                            )
                        )
                    db.session.commit()
                    success_message = "Submission marked Not Codeable by data manager."
                    if odk_sync_result.success:
                        success_message += " ODK Central was flagged for revision."
                    else:
                        flash(
                            "Submission was saved locally, but ODK Central "
                            "could not be updated automatically. "
                            f"{odk_sync_result.error_message}",
                            "warning",
                        )
                    flash(success_message, "success")
                    form = VaDataManagerReviewForm()
                    active_dm_review = db.session.scalar(
                        sa.select(VaDataManagerReview).where(
                            VaDataManagerReview.va_sid == va_sid,
                            VaDataManagerReview.va_dmreview_status == VaStatuses.active,
                        )
                    )
                    submission_workflow = WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER
                elif active_dm_review:
                    form.va_dmreview_reason.data = active_dm_review.va_dmreview_reason
                    form.va_dmreview_other.data = active_dm_review.va_dmreview_other
            elif active_dm_review:
                form.va_dmreview_reason.data = active_dm_review.va_dmreview_reason
                form.va_dmreview_other.data = active_dm_review.va_dmreview_other

            va_previouscategory, va_nextcategory = category_service.get_category_neighbours(
                _form_type_code,
                va_action,
                visible_category_codes,
                va_partial,
            )
            return render_template(
                "va_formcategory_partials/category_data_manager_triage.html",
                category_config=category_service.get_category_config(
                    _form_type_code,
                    va_action,
                    va_partial,
                ),
                va_action=va_action,
                va_actiontype=va_actiontype,
                va_sid=va_sid,
                va_partial=va_partial,
                form=form,
                va_previouscategory=va_previouscategory,
                va_nextcategory=va_nextcategory,
                active_dm_review=active_dm_review,
                active_dm_review_label=(
                    _data_manager_reason_label(active_dm_review.va_dmreview_reason)
                    if active_dm_review
                    else None
                ),
                submission_workflow_state=submission_workflow,
                smartva=smartva,
                success_message=success_message,
                form_error_messages=[],
            )
        _mapping_svc = get_mapping_service()
        category_config = category_service.get_category_config(
            _form_type_code,
            va_action,
            va_partial,
        )
        va_mapping_flip = _mapping_svc.get_flip_labels(_form_type_code)
        va_mapping_info = _mapping_svc.get_info_labels(_form_type_code)
        subcategory_labels = _mapping_svc.get_subcategory_labels(_form_type_code, va_partial)
        subcategory_render_modes = _mapping_svc.get_subcategory_render_modes(
            _form_type_code,
            va_partial,
        )
        section = get_section_data(
            va_submission=va_submission,
            active_version=_active_version,
            form_type_code=_form_type_code,
            va_action=va_action,
            va_partial=va_partial,
            category_config=category_config,
            visible_category_codes=visible_category_codes,
            user=current_user,
        )
        summary_items = section["summary_items"]
        va_processedcategorydata = section["va_processedcategorydata"]
        cod_attachments_data = section["cod_attachments_data"]
        cod_attachments_labels = section["cod_attachments_labels"]
        cod_attachments_render_modes = section["cod_attachments_render_modes"]
        cod_health_history_data = section["cod_health_history_data"]
        cod_health_history_labels = section["cod_health_history_labels"]
        smartva = section["smartva"]
        va_previouscategory, va_nextcategory = category_service.get_category_neighbours(
            _form_type_code,
            va_action,
            visible_category_codes,
            va_partial,
        )
        artifacts = get_case_artifacts(
            va_sid=va_sid,
            va_partial=va_partial,
            va_action=va_action,
            va_actiontype=va_actiontype,
            project=project,
            user_id=current_user.user_id,
        )
        va_reviewer_final_assess = artifacts.va_reviewer_final_assess
        va_reviewer_initial_assess = artifacts.va_reviewer_initial_assess
        va_usernote = get_active_note(current_user.user_id, va_sid)
        template_name = f"va_formcategory_partials/{va_partial}.html"
        if category_config and category_config.render_mode == "table_sections":
            template_name = "va_formcategory_partials/category_table_sections.html"
        elif category_config and category_config.render_mode == "health_history_summary":
            template_name = "va_formcategory_partials/category_health_history_summary.html"
        elif category_config and category_config.render_mode == "attachments":
            template_name = "va_formcategory_partials/category_attachments.html"
        elif category_config and category_config.render_mode == "workflow_panel":
            template_name = "va_formcategory_partials/category_va_cod_assessment.html"
        elif category_config and category_config.render_mode == "data_manager_panel":
            template_name = "va_formcategory_partials/category_data_manager_triage.html"
        doris_source = None
        masked_reviewer_doris = {}
        if _is_doris(project_mode) and not _is_masked(project_mode):
            if va_action == "vareview" and va_reviewer_final_assess:
                doris_source = va_reviewer_final_assess
            else:
                doris_source = get_authoritative_final_assessment(va_sid)
        elif (
            project_mode == "masked_doris"
            and va_action == "vareview"
            # Only an active review renders the editor; a view skips the queries.
            and va_actiontype in {"vastartreviewing", "varesumereviewing"}
            and category_config
            and category_config.render_mode == "workflow_panel"
        ):
            doris_source, masked_reviewer_doris = _masked_reviewer_doris_context(
                va_sid, va_reviewer_initial_assess, smartva
            )
        # Only the workflow panel carries the editor; other categories skip
        # the payload read.
        doris_initial_certificate, doris_prefill_provenance = _doris_initial(
            doris_source.doris_certificate
            if doris_source and doris_source.doris_certificate
            else None,
            va_submission
            if category_config and category_config.render_mode == "workflow_panel"
            else None,
            project_mode,
        )
        response = make_response(render_template(
            template_name,
            instance_name = va_submission.va_uniqueid_masked,
            category_data = va_processedcategorydata,
            category_config = category_config,
            subcategory_labels = subcategory_labels,
            subcategory_render_modes = subcategory_render_modes,
            va_previouscategory = va_previouscategory,
            va_nextcategory = va_nextcategory,
            flip_list = va_mapping_flip,
            info_list = va_mapping_info,
            va_action = va_action,
            va_actiontype = va_actiontype,
            va_sid = va_sid,
            va_partial = va_partial,
            summary = va_submission.va_summary,
            summary_items = summary_items,
            reviewobject = artifacts.reviewobject,
            vafinexists = artifacts.vafinexists,
            vaerrexists = artifacts.vaerrexists,
            vainiexists = artifacts.vainiexists,
            va_final_assess = artifacts.va_final_assess,
            va_initial_assess = artifacts.va_initial_assess,
            va_reviewer_initial_assess=va_reviewer_initial_assess,
            va_reviewer_final_assess=va_reviewer_final_assess,
            va_coder_review = artifacts.va_coder_review,
            smartva = smartva,
            da_va_final_assess = artifacts.da_va_final_assess,
            da_va_initial_assess = artifacts.da_va_initial_assess,
            da_va_coder_review = artifacts.da_va_coder_review,
            narrative_qa_enabled = artifacts.narrative_qa_enabled,
            social_autopsy_enabled = artifacts.social_autopsy_enabled,
            va_narrative_assessment = artifacts.va_narrative_assessment,
            social_autopsy_analysis_questions = SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS,
            va_social_autopsy_analysis = artifacts.va_social_autopsy_analysis,
            social_autopsy_selected_pairs = artifacts.social_autopsy_selected_pairs,
            next_block_message = artifacts.next_block_message,
            cod_attachments_data = cod_attachments_data,
            cod_attachments_labels = cod_attachments_labels,
            cod_attachments_render_modes = cod_attachments_render_modes,
            cod_health_history_data = cod_health_history_data,
            cod_health_history_labels = cod_health_history_labels,
            va_usernote = va_usernote,
            project_mode=project_mode,
            doris_initial_certificate=doris_initial_certificate,
            doris_prefill_provenance=doris_prefill_provenance,
            doris_process_url=f"/api/v1/doris-clinical/process/{va_sid}",
            doris_terms_url=f"/api/v1/doris-clinical/terms/{va_sid}",
            doris_codeinfo_url=f"/api/v1/doris-clinical/codeinfo/{va_sid}",
            doris_selection_check_url=(
                f"/api/v1/doris-clinical/selection-check/{va_sid}"
            ),
            **masked_reviewer_doris,
        ))
        return _apply_partial_cache_policy(response, va_partial, va_action)
    if va_action in _READ_ONLY_ACTIONS and va_partial not in _READ_ONLY_EXTRA_PARTIALS:
        # A read-only page has no coding forms: their GET renders the DORIS
        # prefill and prior certificates from the raw payload (PII).
        va_permission_abortwithflash("This view is read-only.", 403)
    if va_partial == "vareviewform":
        # Narrative Quality Assessment (NQA) — supporting artifact only.
        #
        # NQA is an optional, project-level feature that can be enabled for any
        # form. It collects narrative quality indicators and an overall quality
        # decision (accepted/rejected) from the reviewer during their session.
        #
        # NQA is a supporting artifact in the same category as Social Autopsy
        # Analysis. It does NOT affect the submission workflow state machine.
        # Do NOT add workflow transitions here. The reviewer workflow state
        # (reviewer_coding_in_progress -> reviewer_finalized) is managed by the
        # reviewer's final-COD submission path, not by NQA completion.
        #
        # Persistence rules (per coding-workflow-state-machine policy):
        # - NQA does NOT persist through initial first-pass coding timeout reversion
        # - NQA DOES persist across recode attempts
        # - NQA artifacts created via demo coding are cleaned up on demo expiry
        form = VaReviewerReviewForm()
        if request.method == "POST":
            # NQA is the reviewer's session artifact: only while holding it.
            va_permission_ensureallocation(va_sid, "reviewing")
        if form.validate_on_submit():
            _, active_payload_version = get_submission_with_current_payload(
                va_sid,
                for_update=True,
            )
            existing_review = db.session.scalar(
                sa.select(VaReviewerReview).where(
                    VaReviewerReview.va_sid == va_sid,
                    VaReviewerReview.va_rreview_by == current_user.user_id,
                    VaReviewerReview.payload_version_id
                    == active_payload_version.payload_version_id,
                    VaReviewerReview.va_rreview_status == VaStatuses.active,
                )
            )
            if existing_review:
                existing_review.va_rreview_narrpos = form.va_rreview_narrpos.data
                existing_review.va_rreview_narrneg = form.va_rreview_narrneg.data
                existing_review.va_rreview_narrchrono = form.va_rreview_narrchrono.data
                existing_review.va_rreview_narrdoc = form.va_rreview_narrdoc.data
                existing_review.va_rreview_narrcomorb = form.va_rreview_narrcomorb.data
                existing_review.va_rreview = form.va_rreview.data
                existing_review.va_rreview_fail = form.va_rreview_fail.data.strip() or None
                existing_review.va_rreview_remark = (
                    form.va_rreview_remark.data.strip() or None
                )
                existing_review.payload_version_id = (
                    active_payload_version.payload_version_id
                )
                review_row = existing_review
                audit_operation = "u"
                audit_action = "reviewer review updated"
            else:
                deactivate_other_active_reviewer_reviews(
                    va_sid,
                    current_user.user_id,
                    audit_byrole="reviewer",
                    audit_by=current_user.user_id,
                )
                review_row = VaReviewerReview(
                    va_sid=va_sid,
                    va_rreview_by=current_user.user_id,
                    payload_version_id=active_payload_version.payload_version_id,
                    va_rreview_narrpos=form.va_rreview_narrpos.data,
                    va_rreview_narrneg=form.va_rreview_narrneg.data,
                    va_rreview_narrchrono=form.va_rreview_narrchrono.data,
                    va_rreview_narrdoc=form.va_rreview_narrdoc.data,
                    va_rreview_narrcomorb=form.va_rreview_narrcomorb.data,
                    va_rreview=form.va_rreview.data,
                    va_rreview_fail=form.va_rreview_fail.data.strip() or None,
                    va_rreview_remark=form.va_rreview_remark.data.strip() or None,
                )
                db.session.add(review_row)
                audit_operation = "c"
                audit_action = "reviewer review saved"
            if existing_review:
                deactivate_other_active_reviewer_reviews(
                    va_sid,
                    current_user.user_id,
                    keep_id=review_row.va_rreview_id,
                    audit_byrole="reviewer",
                    audit_by=current_user.user_id,
                )
            # NQA save — do NOT release the reviewing allocation here.
            # Allocation is released only when the reviewer submits their
            # final COD via submit_reviewer_final_cod() in reviewer_coding_service.
            db.session.flush()
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=va_sid,
                    va_audit_byrole="reviewer",
                    va_audit_by=current_user.user_id,
                    va_audit_operation=audit_operation,
                    va_audit_action=audit_action,
                    va_audit_entityid=review_row.va_rreview_id,
                )
            )
            db.session.commit()

            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = current_user.landing_url()
                flash("Review submitted successfully!", "success")
                return response
        return render_template(
            f"va_form_partials/{va_partial}.html", form = form, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid
        )
    if va_partial == "workflow_history":
        events = db.session.scalars(
            sa.select(VaSubmissionWorkflowEvent)
            .where(VaSubmissionWorkflowEvent.va_sid == va_sid)
            .order_by(VaSubmissionWorkflowEvent.event_created_at)
        ).all()
        return render_template(
            "va_form_partials/workflow_history.html",
            va_sid=va_sid,
            events=events,
        )
    if va_partial == "vainitialasses":
        if request.method == "POST":
            # Step 1 writes a coder-attributed row and moves the workflow, so
            # only the coder holding this submission's coding allocation saves
            # it, whichever action's validator admitted the request.
            if va_action != "vacode":
                va_permission_abortwithflash("Only the assigned coder can save Step 1.", 403)
            va_permission_ensureallocation(va_sid, "coding")
            if get_submission_workflow_state(va_sid) not in {
                WORKFLOW_CODING_IN_PROGRESS,
                WORKFLOW_CODER_STEP1_SAVED,
            }:
                va_permission_abortwithflash("This submission is not open for Step 1.", 409)
        form = VaInitialAssessmentForm()
        save_clicked = form.va_save_assessment.data
        not_codeable_clicked = form.va_not_codeable.data
        form.va_other_conditions.choices = other_conditions_choices(va_payload_data)
        # Masked DORIS takes the immediate COD from the certificate, so the
        # simple form's required fields are not posted; CSRF is still
        # enforced app-wide by CSRFProtect.
        if save_clicked and (project_mode == "masked_doris" or form.validate_on_submit()):
            if project_mode == "masked_doris":
                save_kwargs = _doris_form_kwargs()
                save_kwargs["antecedent_cod"] = request.form.get("va_antecedent_cod")
            else:
                save_kwargs = {
                    "immediate_cod": form.va_immediate_cod.data,
                    "antecedent_cod": form.va_antecedent_cod.data,
                    "other_conditions": form.va_other_conditions.data,
                    "payload_data": va_payload_data,
                }
            try:
                saved = submit_coder_initial_cod(
                    current_user, va_sid, actiontype=va_actiontype, **save_kwargs
                )
            except CoderCodingError as exc:
                if exc.code != "invalid_cod" or not exc.fields:
                    return _coder_error_response(exc)
                for field_name, message in zip(exc.fields, exc.messages):
                    getattr(form, f"va_{field_name}").errors.append(message)
                return render_template(
                    f"va_form_partials/{va_partial}.html",
                    form=form,
                    va_action=va_action,
                    va_actiontype=va_actiontype,
                    va_sid=va_sid,
                    pre_immediate_cod=form.va_immediate_cod.data,
                    pre_antecedent_cod=form.va_antecedent_cod.data,
                )
            new_review = saved.assessment
            form1 = VaFinalAssessmentForm()
            smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
            # Step 1 is saved; Step 2 would only be refused at save time.
            if _nqa_blocks_final(va_sid, va_action, project):
                return render_template(
                    "va_form_partials/_nqa_required_notice.html",
                    va_sid=va_sid,
                    va_action=va_action,
                    va_actiontype=va_actiontype,
                    step1_saved=True,
                )
            step2_context = (
                _masked_doris_step2_context(new_review, smartva)
                if project_mode == "masked_doris"
                else {}
            )
            return render_template("va_form_partials/vafinalasses.html", form = form1, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, smartva=smartva, va_immediate_cod = new_review.va_immediate_cod or None, va_antecedent_cod = new_review.va_antecedent_cod or None, va_other_conditions = new_review.va_other_conditions or None, step1_resaved=saved.resaved, project_mode=project_mode, **step2_context)
        elif not_codeable_clicked:
            form2 = VaCoderReviewForm()
            return render_template("va_form_partials/vacoderreview.html", form = form2, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid)
        # GET — pre-populate from any existing active initial assessment
        existing_assess = get_step1_prefill(
            va_sid,
            current_user.user_id,
            va_action,
            recode_resume=va_actiontype == "varesumecoding",
        )
        doris_initial_certificate, doris_prefill_provenance = _doris_initial(
            existing_assess.doris_certificate
            if existing_assess and existing_assess.doris_certificate
            else None,
            va_submission,
            project_mode,
        )
        pre_immediate_cod = None
        pre_antecedent_cod = None
        if existing_assess:
            pre_immediate_cod = existing_assess.va_immediate_cod
            pre_antecedent_cod = existing_assess.va_antecedent_cod
            form.va_immediate_cod.data = pre_immediate_cod
            form.va_antecedent_cod.data = pre_antecedent_cod
            if existing_assess.va_other_conditions:
                form.va_other_conditions.data = existing_assess.va_other_conditions.split(" | ")
        # A saved masked DORIS Step 1 reopens with its result shown so the
        # coder can continue to Step 2 without processing again. No process
        # token is minted here: the result is display-only, and saving a
        # changed Step 1 still needs a fresh Process (digitva-0n3.4).
        saved_doris_processing = None
        if (
            project_mode == "masked_doris"
            and existing_assess is not None
            and existing_assess.va_iniassess_status == VaStatuses.active
            and existing_assess.doris_result is not None
        ):
            saved_doris_processing = {
                "certificate": existing_assess.doris_certificate,
                "doris": existing_assess.doris_result,
                "codedit": existing_assess.codedit_result,
                "final_choice": existing_assess.va_antecedent_cod or "",
            }
        return render_template(
            f"va_form_partials/{va_partial}.html",
            form=form,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            pre_immediate_cod=pre_immediate_cod,
            pre_antecedent_cod=pre_antecedent_cod,
            project_mode=project_mode,
            # No SmartVA in masked Step 1: the certificate is entered blind.
            doris_initial_certificate=doris_initial_certificate,
            doris_prefill_provenance=doris_prefill_provenance,
            doris_initial_processing=saved_doris_processing,
            doris_process_url=f"/api/v1/doris-clinical/process/{va_sid}",
            doris_terms_url=f"/api/v1/doris-clinical/terms/{va_sid}",
            doris_codeinfo_url=f"/api/v1/doris-clinical/codeinfo/{va_sid}",
            doris_selection_check_url=(
                f"/api/v1/doris-clinical/selection-check/{va_sid}"
            ),
        )
    if va_partial == "vafinalasses":
        if request.method == "GET" and _nqa_blocks_final(va_sid, va_action, project):
            return render_template(
                "va_form_partials/_nqa_required_notice.html",
                va_sid=va_sid,
                va_action=va_action,
                va_actiontype=va_actiontype,
            )
        form1 = VaFinalAssessmentForm()
        smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
        va_initial_assess = db.session.scalar(
            sa.select(VaInitialAssessments)
            .where(
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
                VaInitialAssessments.va_sid == va_sid,
                VaInitialAssessments.va_iniassess_by == current_user.user_id,
            )
            .order_by(VaInitialAssessments.va_iniassess_createdat.desc())
        )
        prior_authoritative_final = get_authoritative_final_assessment(va_sid)
        prior_final_initial = None
        if (
            prior_authoritative_final
            and prior_authoritative_final.source_initial_assessment_id
        ):
            prior_final_initial = db.session.get(
                VaInitialAssessments,
                prior_authoritative_final.source_initial_assessment_id,
            )

        def _render_final_assessment_form(error_messages=None):
            submitted_unmasked = request.method == "POST" and not _is_masked(project_mode)
            submitted_certificate = None
            render_error_messages = (
                error_messages
                if error_messages is not None
                else [message for messages in form1.errors.values() for message in messages]
            )
            submitted_processing = None
            if submitted_unmasked and project_mode == "unmasked_doris":
                try:
                    submitted_certificate = _json_form_value("doris_certificate")
                    # A save refused for another reason (for example a
                    # missing NQA) keeps the processed result and the chosen
                    # final UCOD on screen. The signed token is checked
                    # again at the next save, as for any other submission.
                    doris_result = _json_form_value("doris_result")
                    codedit_result = _json_form_value("codedit_result")
                    if (
                        submitted_certificate
                        and doris_result
                        and codedit_result
                        and request.form.get("doris_process_token")
                        and request.form.get("doris_result_digest")
                    ):
                        submitted_processing = {
                            "certificate": submitted_certificate,
                            "doris": doris_result,
                            "codedit": codedit_result,
                            "process_token": request.form.get("doris_process_token"),
                            "result_digest": request.form.get("doris_result_digest"),
                            "final_choice": request.form.get("va_conclusive_cod") or "",
                        }
                except ValueError as exc:
                    # Do not silently fall back to a previous saved certificate:
                    # that can make an invalid client payload look like the
                    # certificate the coder just submitted.
                    submitted_certificate = {}
                    render_error_messages = [*render_error_messages, str(exc)]
            prior_certificate = (
                prior_authoritative_final.doris_certificate
                if prior_authoritative_final
                else None
            )
            prior_immediate = (
                prior_authoritative_final.va_immediate_cod
                if prior_authoritative_final
                else None
            )
            prior_other_conditions = (
                prior_authoritative_final.va_other_conditions
                if prior_authoritative_final
                else None
            )
            # Only unmasked DORIS shows a certificate here; masked Step 2
            # confirms the cause without one.
            doris_initial_certificate, doris_prefill_provenance = _doris_initial(
                submitted_certificate
                if submitted_certificate is not None
                else prior_certificate or None,
                va_submission if project_mode == "unmasked_doris" else None,
                project_mode,
            )
            return render_template(
                f"va_form_partials/{va_partial}.html",
                form=form1,
                va_action=va_action,
                va_actiontype=va_actiontype,
                va_sid=va_sid,
                smartva=smartva,
                va_immediate_cod=va_initial_assess.va_immediate_cod if va_initial_assess else None,
                va_antecedent_cod=va_initial_assess.va_antecedent_cod if va_initial_assess else None,
                va_other_conditions=va_initial_assess.va_other_conditions if va_initial_assess else None,
                pre_immediate_cod=(
                    request.form.get("va_immediate_cod")
                    if submitted_unmasked
                    else prior_immediate
                ),
                pre_other_conditions=(
                    request.form.get("va_other_conditions")
                    if submitted_unmasked
                    else prior_other_conditions
                ),
                pre_conclusive_cod=(
                    request.form.get("va_conclusive_cod")
                    if submitted_unmasked
                    else prior_authoritative_final.va_conclusive_cod
                    if prior_authoritative_final
                    else None
                ),
                previous_final_conclusive_cod=(
                    prior_authoritative_final.va_conclusive_cod
                    if prior_authoritative_final
                    else None
                ),
                previous_final_immediate_cod=(
                    prior_final_initial.va_immediate_cod
                    if prior_final_initial
                    else None
                ),
                previous_final_antecedent_cod=(
                    prior_final_initial.va_antecedent_cod
                    if prior_final_initial
                    else None
                ),
                form_error_messages=render_error_messages,
                pre_remark=(
                    request.form.get("va_finassess_remark")
                    if submitted_unmasked
                    else None
                ),
                project_mode=project_mode,
                doris_initial_certificate=doris_initial_certificate,
                doris_prefill_provenance=doris_prefill_provenance,
                doris_initial_processing=submitted_processing,
                doris_process_url=f"/api/v1/doris-clinical/process/{va_sid}",
                doris_terms_url=f"/api/v1/doris-clinical/terms/{va_sid}",
                doris_codeinfo_url=f"/api/v1/doris-clinical/codeinfo/{va_sid}",
                doris_selection_check_url=(
                    f"/api/v1/doris-clinical/selection-check/{va_sid}"
                ),
                **(
                    _masked_doris_step2_context(va_initial_assess, smartva)
                    if project_mode == "masked_doris"
                    else {}
                ),
            )

        if form1.validate_on_submit():
            if project_mode == "unmasked_doris":
                doris_kwargs = _doris_form_kwargs()
            elif project_mode == "masked_doris":
                # Step 2 refuses any envelope; the service says so.
                doris_kwargs = {
                    name: request.form.get(name) for name in _DORIS_ENVELOPE_FIELDS
                }
            else:
                doris_kwargs = {}
            try:
                saved = submit_coder_final_cod(
                    current_user,
                    va_sid,
                    conclusive_cod=form1.va_conclusive_cod.data,
                    remark=form1.va_finassess_remark.data,
                    immediate_cod=request.form.get("va_immediate_cod"),
                    other_conditions=request.form.get("va_other_conditions"),
                    cod_search_id=request.form.get("cod_search_id"),
                    cod_chosen_code=request.form.get("cod_chosen_code"),
                    cod_chosen_rank=request.form.get("cod_chosen_rank"),
                    actiontype=va_actiontype,
                    **doris_kwargs,
                )
            except CoderCodingError as exc:
                if exc.code != "final_blocked" and exc.message != STEP1_REQUIRED_MESSAGE:
                    return _coder_error_response(exc)
                if request.headers.get("HX-Request"):
                    return _render_final_assessment_form(exc.messages)
                for message in exc.messages:
                    flash(message, "warning")
                return redirect(request.referrer or url_for("coding.dashboard"))
            if saved.tester:
                flash(TESTER_SAVED_MESSAGE, "success")
                if request.headers.get("HX-Request"):
                    response = jsonify(success=True)
                    response.headers["HX-Redirect"] = url_for("coding.dashboard")
                    return response
                return redirect(url_for("coding.dashboard"))
            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = url_for('coding.dashboard')
                flash("VA Coding submitted successfully!", "success")
                return response
        return _render_final_assessment_form()
    if va_partial == "vausernote":
        form = VaUsernoteForm()
        if form.validate_on_submit():
            save_note(current_user.user_id, va_sid, form.va_note_content.data)
            obb_response = render_template("va_intermediate_partials/va_note_notification.html", message="Note Saved!")
            main_response = render_template(f"va_form_partials/{va_partial}.html", va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, form=form)
            return obb_response + main_response
        va_usernote = get_active_note(current_user.user_id, va_sid)
        form.va_note_content.data = va_usernote.note_content if va_usernote else ""
        return render_template(f"va_form_partials/{va_partial}.html", va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, form=form)
    if va_partial == "vacoderreview":
        form = VaCoderReviewForm()
        def _render_coder_review_form(error_messages=None):
            return render_template(
                f"va_form_partials/{va_partial}.html",
                va_action=va_action,
                va_actiontype=va_actiontype,
                va_sid=va_sid,
                form=form,
                form_error_messages=error_messages or [],
            )
        if request.method == "POST":
            # Not codeable releases the coder's allocation below; without one
            # there is nothing to release and nobody to attribute it to.
            va_permission_ensureallocation(va_sid, "coding")
        if form.validate_on_submit():
            try:
                saved = submit_coder_not_codeable(
                    current_user,
                    va_sid,
                    reason=form.va_creview_reason.data,
                    other=form.va_creview_other.data,
                    actiontype=va_actiontype,
                )
            except CoderCodingError as exc:
                return _coder_error_response(exc)
            if saved.tester:
                flash(TESTER_SAVED_MESSAGE, "success")
                if request.headers.get("HX-Request"):
                    response = jsonify(success=True)
                    response.headers["HX-Redirect"] = url_for("coding.dashboard")
                    return response
                return redirect(url_for("coding.dashboard"))
            success_message = "Not Codeable saved locally."
            warning_message = None
            if saved.odk_synced:
                success_message += " ODK Central was flagged for revision."
            else:
                warning_message = (
                    "Not Codeable was saved locally, but ODK Central could not be "
                    f"updated automatically. {saved.odk_error}"
                )
            flash(success_message, "success")
            if warning_message:
                flash(warning_message, "warning")
            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = url_for('coding.dashboard')
                return response
        return _render_coder_review_form()
    abort(404)




# Everyone who may view a submission may receive its attachments; the
# submission-level VIEW check is attachment_service's. Role names stay
# literal so role_required's decoration-time validation can vouch for them.


@va_form.route('/attachment/<path:storage_name_raw>')
@role_required(
    "coder", "coding_tester", "reviewer", "data_manager", "site_pi",
    "project_pi", "collaborator", "collaborator_pii", "admin",
)
def serve_attachment(storage_name_raw):
    """Serve an attachment by opaque storage_name token.

    Security contract (docs/policy/attachment-storage.md):
      1. @role_required handles auth + active-status + role gate
      2. Format validation → 404
      3. Record lookup (exists_on_odk=True only) → 404
      4. Submission-level authorization for the current user → 403
      5. Delivery (local or Central-backed, no-store) → 200 / 404 / 502 / 503

    The checks and the delivery are the attachment service's (the same ones
    ``/api/v1/attachments`` runs); this route learns nothing about where the
    bytes live.
    """
    record = attachment_service.authorize_token_attachment(current_user, storage_name_raw)
    if isinstance(record, int):
        abort(record)

    return attachment_service.deliver(record)


@va_form.route('/media/<va_form_id>/<va_filename>')
@role_required(
    "coder", "coding_tester", "reviewer", "data_manager", "site_pi",
    "project_pi", "collaborator", "collaborator_pii", "admin",
)
def serve_media(va_form_id, va_filename):
    # DEPRECATED: rendered URLs are /api/v1/attachments (legacy/<form>/<file> for these rows).
    # Kept for backward compatibility during migration (storage_name IS NULL rows).
    log.info("serve_media legacy hit: form=%s file=%s", va_form_id, va_filename)

    # Ownership, access and filename checks are attachment_service's, shared
    # with /api/v1/attachments/legacy.
    record = attachment_service.authorize_legacy_attachment(
        current_user, va_form_id, va_filename
    )
    if record == 403:
        va_permission_abortwithflash(f"You don't have permissions to access the media files for '{va_form_id}'", 403)
    if isinstance(record, int):
        abort(record)

    return attachment_service.deliver_legacy_media(record)





# # * api call to fetch coding / smartva information for some sid / va form
# @coding.route("/form/<sid>/coding", methods=['GET', 'POST'])
# def get_smartva(sid):
#     # check if form exists
#     form_va = db.session.scalar(sa.select(VaSubmissions).where(VaSubmissions.sid == sid))
#     if not form_va:
#         return "Form not found", 404
#     # load the smartva result for sid
#     smartva_result = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.sid == sid) & (VaSmartvaResults.status == "active")))
#     # return 404 if result not found
#     if not smartva_result:
#         return "Form not found", 404
#     # check for existing assessment
#     existing_assessment = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.sid == sid) & (VaFinalAssessments.status == "active")))
#     if existing_assessment:
#         icd_status = db.session.scalar(sa.select(VaIcdCodes).where((VaIcdCodes.icd_code == existing_assessment.icd_code_id)))
#     else:
#         icd_status = None
#     # create form instance
#     form = VaFinalAssessmentForm()
#     form.sid.data = sid
#     # render data
#     return render_template(
#         "partials/category_smartva.html",
#         smartva = smartva_result,
#         sid = sid,
#         summary = form_va.json_summary,
#         existing_assessment=existing_assessment,
#         form=form,
#         icd_status=icd_status.description if icd_status else None
#     )


# # Deprecated as of 2026-04-20:
# # legacy `VaIcdCodes` search path retained only as commented reference.
# # Runtime ICD search now uses `mas_icd10_2019_2`.
# # * api call to search for allotable ICD codes
# @coding.route('/search_icd_codes')
# def search_icd_codes():
#     search_term = request.args.get('q', '')
#     page = int(request.args.get('page', 1))
#     per_page = 20

#     query = VaIcdCodes.query

#     if search_term:
#         query = query.filter(
#             db.or_(
#                 VaIcdCodes.icd_code.ilike(f'%{search_term}%'),
#                 VaIcdCodes.icd_to_display.ilike(f'%{search_term}%'),
#                 VaIcdCodes.description.ilike(f'%{search_term}%')
#             )
#         )

#     pagination = query.paginate(page=page, per_page=per_page, error_out=False)

#     results = []
#     for icd in pagination.items:
#         results.append({
#             'id': icd.icd_code,
#             'text': icd.icd_to_display
#         })

#     return jsonify({
#         'results': results,
#         'pagination': {
#             'more': pagination.has_next
#         }
#     })

# @coding.route("/api/<sid>/save-assessment", methods=['POST'])
# def save_assessment(sid):
#     """POST - Save assessment data"""
#     form = VaFinalAssessmentForm()

#     if form.validate_on_submit():
#         try:
#             existing_assessment = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.sid == sid) & (VaFinalAssessments.status == "active")))

#             error_report_value = form.error_report.data.strip() if form.error_report.data else ""

#             print(f"Error report value (cleaned): '{error_report_value}'")
#             print(f"Error report length: {len(error_report_value)}")

#             if error_report_value:

#                 # Handle error report
#                 if existing_assessment:
#                     assessment = existing_assessment
#                 else:
#                     assessment = VaFinalAssessments(sid=sid)
#                     db.session.add(assessment)

#                 assessment.error_reported = True
#                 assessment.error_report = error_report_value  # ✅ Use cleaned value
#                 assessment.icd_code_id = None
#                 assessment.confidence = None
#                 assessment.comment = None

#                 flash("Error reported successfully. Please continue with another submission.", "success")

#             else:
#                 # Handle regular assessment
#                 if existing_assessment:
#                     assessment = existing_assessment
#                 else:
#                     assessment = VaFinalAssessments(sid=sid)
#                     db.session.add(assessment)

#                 assessment.error_reported = False
#                 assessment.error_report = None
#                 assessment.icd_code_id = form.icd_code_id.data if form.icd_code_id.data else None
#                 assessment.confidence = form.confidence.data
#                 assessment.comment = form.comment.data
#                 flash("Assessment saved successfully. Please continue with another submission.", "success")

#             assessment.status = "active"

#             db.session.commit()

#             saved_assessment = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.sid == sid) & (VaFinalAssessments.status == "active")))

#             # Return to GET route to show updated data
#             return redirect(url_for('main.vacoding', sid=sid))

#         except Exception as e:
#             db.session.rollback()
#             print(f"ERROR during save: {str(e)}")
#             flash(f'Error saving assessment: {str(e)}', 'danger')
#             return redirect(url_for('main.vacoding', sid=sid))

#     else:
#         # Validation failed - show errors
#         for field, errors in form.errors.items():
#             print(f"Field {field} errors:", errors)
#             for error in errors:
#                 flash(f'{field}: {error}', 'danger')
