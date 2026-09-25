import logging
import re
import uuid

log = logging.getLogger(__name__)
import sqlalchemy as sa
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import cache as flask_cache
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
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUsernotes,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_service, coding_search_telemetry_service
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.coder_dashboard_service import bust_coder_dashboard_cache
from app.services.coding_service import get_project_for_submission as _get_project_for_submission
from app.services.demo_project_service import get_demo_expiry_for_submission
from app.services.field_mapping_service import get_mapping_service
from app.services.final_cod_authority_service import (
    complete_recode_episode,
    get_active_recode_episode,
    get_authoritative_final_assessment,
    get_authoritative_final_cod_record,
    upsert_final_cod_authority,
)
from app.services.icd_coding_value import (
    build_icd11_provenance_for_values,
    validate_coding_value_for_submission,
)
from app.services.odk_review_service import sync_not_codeable_review_state
from app.services.payload_bound_coding_artifact_service import (
    deactivate_other_active_reviewer_reviews,
    get_current_payload_narrative_assessment,
    get_current_payload_reviewer_review,
    get_current_payload_social_autopsy_analysis,
    get_submission_with_current_payload,
)
from app.services.reviewer_final_assessment_service import (
    get_latest_active_reviewer_final_assessment,
    get_latest_active_reviewer_initial_assessment,
)
from app.services.social_autopsy_analysis_service import SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
from app.services.submission_payload_version_service import get_active_payload_version
from app.services.submission_summary_service import build_submission_summary
from app.services.viewer_pii_service import should_redact_pii
from app.services.workflow.definition import (
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_SCREENING_PENDING,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    sync_submission_workflow_from_legacy_records,
)
from app.services.workflow.transitions import (
    WorkflowTransitionError,
    coder_actor,
    data_manager_actor,
    mark_coder_finalized,
    mark_coder_not_codeable,
    mark_coder_step1_saved,
    mark_data_manager_not_codeable,
    mark_recode_finalized,
)
from app.utils import (
    va_get_form_type_code_for_form,
    va_permission_abortwithflash,
    va_render_processcategorydata,
)
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel

va_form = Blueprint("va_form", __name__)

_SECTION_CACHE_TIMEOUT = 1800  # 30 minutes


def _section_data_cache_key(va_sid: str, va_partial: str) -> str:
    """Cache key for rendered category data (payload-derived, not user-specific)."""
    return f"form_data:{va_sid}:{va_partial}"


def _response_contains_user_specific_artifacts(va_partial: str, va_action: str) -> bool:
    """Return whether a rendered partial includes user-specific coding artifacts."""
    if va_action not in {"vacode", "vareview"}:
        return False
    return va_partial in {"vanarrationanddocuments", "social_autopsy"}


def _apply_partial_cache_policy(response, va_partial: str, va_action: str):
    """Apply HTTP cache headers for rendered form partials."""
    response.cache_control.private = True
    if _response_contains_user_specific_artifacts(va_partial, va_action):
        response.cache_control.no_store = True
        response.cache_control.max_age = 0
    else:
        response.cache_control.max_age = 300  # 5 minutes — PHI data
    return response


def _invalidate_section_data_cache(va_sid: str) -> None:
    """Drop all cached form-data entries for a submission."""
    sub = db.session.get(VaSubmissions, va_sid)
    if not sub:
        return
    _ftc = va_get_form_type_code_for_form(sub.va_form_id)
    _pv = get_active_payload_version(va_sid)
    _pd = _pv.payload_data if _pv else None
    visible = get_visible_category_codes(_pd, sub.va_form_id)
    for _partial in visible:
        flask_cache.delete(_section_data_cache_key(va_sid, _partial))


def _demo_expiry_for_actiontype(va_sid: str, va_actiontype: str):
    """Return the demo artifact expiry timestamp for demo coding saves."""
    return get_demo_expiry_for_submission(va_sid, va_actiontype)


def _get_display_initial_assessment(va_sid: str):
    """Return the initial COD to display for view/history contexts.

    Prefer the current active initial assessment. If the active draft was
    superseded during final COD submission, fall back to the source initial
    assessment linked from the authoritative coder final assessment.
    """
    initial_assessment = db.session.scalar(
        sa.select(VaInitialAssessments).where(
            (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
            & (VaInitialAssessments.va_sid == va_sid)
        )
    )
    if initial_assessment is not None:
        return initial_assessment

    authoritative_coder_final = get_authoritative_final_assessment(va_sid)
    if (
        authoritative_coder_final is None
        or authoritative_coder_final.source_initial_assessment_id is None
    ):
        return None

    return db.session.get(
        VaInitialAssessments,
        authoritative_coder_final.source_initial_assessment_id,
    )


def _is_social_autopsy_enabled_for_submission(va_sid: str, va_action: str = "vacode") -> bool:
    """Return whether the app-owned Social Autopsy analysis form is enabled."""
    project = _get_project_for_submission(va_sid)
    if project is None:
        return True
    if va_action == "vareview":
        return bool(project.reviewer_social_autopsy_enabled)
    return bool(project.social_autopsy_enabled)
adult = [
    "I10 - Essential Hypertension",
    "E11 - Type 2 Diabetes Mellitus",
    "E10 - Type 1 Diabetes Mellitus",
    "E66 - Obesity",
    "N18 - Chronic Kidney Disease",
    "K74 - Chronic Liver Disease",
    "J44 - Chronic Obstructive Pulmonary Disease",
    "J45 - Asthma",
    "E78 - Dyslipidemia",
    "I50 - Congestive Heart Failure",
    "I25 - Coronary Artery Disease",
    "D64 - Chronic Anaemia",
    "F03 - Dementia",
    "I25.2 - Previous Myocardial Infarction",
    "I69 - Previous Stroke/CVA",
    "C80 - Cancer (non-primary, metastasis, history)",
    "B24 - HIV/AIDS",
    "Z86.1 - Past history of tuberculosis",
    "D89 - Immunosuppression",
    "E03 - Hypothyroidism",
    "E05 - Hyperthyroidism",
    "B18 - Chronic Viral Infections (Hepatitis)",
    "I73.9 - Peripheral Vascular Disease",
    "I09 - Chronic Rheumatic Heart Disease",
    "Z98.8 - History of Major Surgery",
    "Z79.3 - Long-term use of Immunosuppressants"
]

neonate = [
    "P07 - Preterm birth",
    "P07.0, P07.1 - Low Birth Weight",
    "P05 - Intrauterine Growth Restriction",
    "P21 - Birth Asphyxia",
    "P36 - Neonatal Sepsis",
    "P23 - Neonatal Pneumonia",
    "P22 - Hyaline Membrane Disease / Respiratory Distress Syndrome",
    "P24.0 - Meconium Aspiration Syndrome",
    "P59 - Neonatal Jaundice",
    "P90 - Neonatal Convulsions",
    "P91.6 - Hypoxic Ischemic Encephalopathy",
    "P80 - Hypothermia of Newborn",
    "P70.4 - Hypoglycemia of Newborn",
    "P52 - Neonatal Hemorrhage",
    "Q20 - Q28 - Congenital Heart Disease",
    "Q00 - Q99 - Congenital Malformations",
    "Q90 - Chromosomal Abnormalities",
    "A33 - Neonatal Tetanus",
    "P37.9 - Neonatal Meningitis",
    "P77 - Necrotizing Enterocolitis",
    "P00.1 - Maternal Diabetes",
    "P00.0 - Maternal Hypertension",
    "P02.7 - Chorioamnionitis",
    "P01.5 - Twin/Multiple Gestation",
    "P35, P37 - Congenital Infections (TORCH)",
    "P58, P59 - Hyperbilirubinemia",
    "P92 - Feeding Problems of Newborn",
    "P04 - Maternal drug use affecting newborn"
]

children = [
    "J06, J20, J21 - Acute Respiratory Infections",
    "J45 - Asthma",
    "D50 - D53 - Anemia",
    "E40 - E46 - Malnutrition",
    "E66 - Obesity",
    "E10, E11 - Diabetes Mellitus (Type 1/2)",
    "G40 - Epilepsy",
    "Q20 - Q28 - Congenital Heart Disease",
    "D57 - Sickle Cell Disease",
    "D56 - Thalassemia",
    "Q90 - Down Syndrome",
    "E84 - Cystic Fibrosis",
    "N18, N04 - Renal Disease",
    "A15 - A19 - Tuberculosis",
    "B20 - B24 - HIV/AIDS",
    "D80 - D89 - Immunodeficiency",
    "I05 - I09 - Rheumatic Heart Disease",
    "G80 - Cerebral Palsy",
    "F84 - Autism Spectrum Disorders",
    "F70 - F79 - Intellectual Disability",
    "C91 - C95, C81 - C85, C00 - C80 - Cancer",
    "D57.3 - Sickle Cell Trait",
    "D56.3 - Thalassemia Trait",
    "Z98.8 - Previous Major Surgery",
    "P07 - History of Prematurity/Low Birth Weight",
    "Z28.3 - Incomplete immunization Status"
]

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


@va_form.route("/<va_sid>/<va_partial>", methods=["GET", "POST"])
@login_required
@va_validate_permissions()
def renderpartial(va_sid, va_partial):
    va_action = request.values.get("action", "vacode")
    va_actiontype = request.values.get("actiontype", "")
    va_submission = db.session.get(VaSubmissions, va_sid)
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
                # Defense-in-depth: the route is already guarded by @role_required("data_manager"),
                # but vadmtriage POSTs arrive via the shared va_form endpoint, so we re-check here.
                if not current_user.is_data_manager():
                    abort(403)
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
        va_mapping_fieldsitepi = _mapping_svc.get_fieldsitepi(_form_type_code)
        va_mapping_choice = _mapping_svc.get_choices(_form_type_code)
        va_mapping_flip = _mapping_svc.get_flip_labels(_form_type_code)
        va_mapping_info = _mapping_svc.get_info_labels(_form_type_code)
        subcategory_labels = _mapping_svc.get_subcategory_labels(_form_type_code, va_partial)
        subcategory_render_modes = _mapping_svc.get_subcategory_render_modes(
            _form_type_code,
            va_partial,
        )
        # --- Cache expensive form-data queries (not user-specific) ---
        # Redaction depends on the viewer's role (should_redact_pii), so the
        # redacted and unredacted renders must not share a cache entry —
        # otherwise whichever viewer renders a section first decides what
        # every later viewer of that section sees. See
        # docs/policy/access-control-model.md, "collaborator".
        _redact_pii = should_redact_pii(current_user)
        _data_cache_key = _section_data_cache_key(va_sid, va_partial)
        if _redact_pii:
            _data_cache_key += ":nopii"
        _cached_data = flask_cache.get(_data_cache_key)
        if _cached_data is not None:
            summary_items = _cached_data["summary_items"]
            va_processedcategorydata = _cached_data["va_processedcategorydata"]
            cod_attachments_data = _cached_data["cod_attachments_data"]
            cod_attachments_labels = _cached_data["cod_attachments_labels"]
            cod_attachments_render_modes = _cached_data["cod_attachments_render_modes"]
            cod_health_history_data = _cached_data["cod_health_history_data"]
            cod_health_history_labels = _cached_data["cod_health_history_labels"]
            smartva = _cached_data["smartva"]
        else:
            # For a no-PII viewer, strip payload fields flagged `is_pii` before
            # they ever reach summary/category rendering, rather than trying to
            # filter the rendered (label-keyed) output afterwards.
            # An unconfirmed PII set means nobody has said which of this form
            # type's fields are personal data, so no field can be trusted not
            # to be: withhold the whole payload rather than redact by an
            # answer that was never given. See
            # docs/policy/access-control-model.md, "The PII set must be
            # confirmed per form type".
            _render_payload_data = va_payload_data
            if _redact_pii and va_payload_data:
                _pii_status = _mapping_svc.get_pii_set_status(_form_type_code)
                if not _pii_status.confirmed:
                    current_app.logger.warning(
                        "pii set unconfirmed | %s | payload withheld",
                        _form_type_code,
                    )
                    _render_payload_data = {}
                else:
                    _render_payload_data = {
                        field_id: value
                        for field_id, value in va_payload_data.items()
                        if field_id not in _pii_status.field_ids
                    }
            summary_items = build_submission_summary(
                _form_type_code,
                _render_payload_data,
            )
            va_datalevel = va_get_render_datalevel(
                va_action,
                _form_type_code,
                visible_category_codes,
            )
            va_processedcategorydata = va_render_processcategorydata(_render_payload_data, va_submission.va_form_id, va_datalevel, va_mapping_choice, va_partial, va_sid=va_submission.va_sid)
            cod_attachments_data = {}
            cod_attachments_labels = {}
            cod_attachments_render_modes = {}
            cod_health_history_data = {}
            cod_health_history_labels = {}
            if category_config and category_config.render_mode == "workflow_panel":
                cod_attachments_data = va_render_processcategorydata(
                    _render_payload_data,
                    va_submission.va_form_id,
                    va_datalevel,
                    va_mapping_choice,
                    "vanarrationanddocuments",
                    va_sid=va_submission.va_sid,
                )
                cod_attachments_labels = _mapping_svc.get_subcategory_labels(
                    _form_type_code,
                    "vanarrationanddocuments",
                )
                cod_attachments_render_modes = _mapping_svc.get_subcategory_render_modes(
                    _form_type_code,
                    "vanarrationanddocuments",
                )
                cod_health_history_data = va_render_processcategorydata(
                    _render_payload_data,
                    va_submission.va_form_id,
                    va_datalevel,
                    va_mapping_choice,
                    "vahealthhistorydetails",
                    va_sid=va_submission.va_sid,
                )
                cod_health_history_labels = _mapping_svc.get_subcategory_labels(
                    _form_type_code,
                    "vahealthhistorydetails",
                )
            smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
            flask_cache.set(_data_cache_key, {
                "summary_items": summary_items,
                "va_processedcategorydata": va_processedcategorydata,
                "cod_attachments_data": cod_attachments_data,
                "cod_attachments_labels": cod_attachments_labels,
                "cod_attachments_render_modes": cod_attachments_render_modes,
                "cod_health_history_data": cod_health_history_data,
                "cod_health_history_labels": cod_health_history_labels,
                "smartva": smartva,
            }, timeout=_SECTION_CACHE_TIMEOUT)
        va_previouscategory, va_nextcategory = category_service.get_category_neighbours(
            _form_type_code,
            va_action,
            visible_category_codes,
            va_partial,
        )
        next_block_message = _get_required_completion_block(
            va_sid,
            va_partial,
            va_action,
            va_actiontype,
        )
        reviewobject = None
        if va_action == "vareview":
            reviewobject = get_current_payload_reviewer_review(
                va_sid,
                current_user.user_id,
            )
        elif va_action == "vacode":
            reviewobject = db.session.scalar(
                sa.select(VaReviewerReview).where(
                    (VaReviewerReview.va_rreview_status == VaStatuses.active)
                    & (VaReviewerReview.va_sid == va_sid)
                )
            )
        authoritative_final_assess = get_authoritative_final_cod_record(va_sid)
        vafinexists = authoritative_final_assess.va_sid if authoritative_final_assess else None
        vaerrexists = db.session.scalar(sa.select(VaCoderReview.va_sid).where((VaCoderReview.va_creview_status == VaStatuses.active)&(VaCoderReview.va_sid == va_sid)))
        # For coding sessions scope vainiexists to the current user — a previous
        # user's active initial assessment must not redirect this user to step 2.
        # For review/view contexts leave it unscoped (show any coder's assessment).
        _ini_filter = [
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            VaInitialAssessments.va_sid == va_sid,
        ]
        if va_action == "vacode":
            _ini_filter.append(VaInitialAssessments.va_iniassess_by == current_user.user_id)
        vainiexists = db.session.scalar(sa.select(VaInitialAssessments.va_sid).where(*_ini_filter))
        va_final_assess = authoritative_final_assess
        va_initial_assess = _get_display_initial_assessment(va_sid)
        va_reviewer_initial_assess = None
        va_reviewer_final_assess = None
        if va_action == "vareview":
            va_reviewer_initial_assess = get_latest_active_reviewer_initial_assessment(
                va_sid,
                current_user.user_id,
            )
            va_reviewer_final_assess = get_latest_active_reviewer_final_assessment(
                va_sid
            )
        va_coder_review = db.session.scalar(sa.select(VaCoderReview).where((VaCoderReview.va_creview_status == VaStatuses.active)&(VaCoderReview.va_sid == va_sid)))
        da_va_final_assess = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.va_finassess_status == VaStatuses.deactive)&(VaFinalAssessments.va_sid == va_sid)&(VaFinalAssessments.va_finassess_by == current_user.user_id)))
        da_va_initial_assess = None
        da_va_coder_review = db.session.scalar(sa.select(VaCoderReview).where((VaCoderReview.va_creview_status == VaStatuses.deactive)&(VaCoderReview.va_sid == va_sid)&(VaCoderReview.va_creview_by == current_user.user_id)))
        # return render_template(
        #     f"va_formcategory_partials/{va_partial}.html",
        #     va_codingplatformid = va_submission.va_uniqueid_masked,
        #     va_processedcategorydata = va_processedcategorydata,
        #     va_previouscategory = va_previouscategory,
        #     va_nextcategory = va_nextcategory,
        #     va_mappingflip = va_mapping_flip,
        #     va_mappinginfo = va_mapping_info,
        # )
        # NQA context (only relevant for vanarrationanddocuments in coding/reviewing)
        _nqa_project = _get_project_for_submission(va_sid) if va_partial == "vanarrationanddocuments" else None
        narrative_qa_enabled = bool(_nqa_project and _nqa_project.narrative_qa_enabled)
        social_autopsy_enabled = (
            _is_social_autopsy_enabled_for_submission(va_sid, va_action)
            if va_partial == "social_autopsy"
            else False
        )
        va_narrative_assessment = None
        if narrative_qa_enabled and va_action in {"vacode", "vareview"}:
            va_narrative_assessment = get_current_payload_narrative_assessment(
                va_sid,
                current_user.user_id,
            )
        va_social_autopsy_analysis = None
        va_usernote = db.session.scalar(
            sa.select(VaUsernotes).where(
                VaUsernotes.note_by == current_user.user_id,
                VaUsernotes.note_vasubmission == va_sid,
                VaUsernotes.note_status == VaStatuses.active,
            )
        )
        if va_partial == "social_autopsy" and va_action in {"vacode", "vareview"} and social_autopsy_enabled:
            va_social_autopsy_analysis = get_current_payload_social_autopsy_analysis(
                va_sid,
                current_user.user_id,
            )
        social_autopsy_selected_pairs = set()
        if va_social_autopsy_analysis:
            social_autopsy_selected_pairs = {
                f"{item.delay_level}::{item.option_code}"
                for item in va_social_autopsy_analysis.selected_options
            }
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
            reviewobject = reviewobject,
            vafinexists = vafinexists,
            vaerrexists = vaerrexists,
            vainiexists = vainiexists,
            va_final_assess = va_final_assess,
            va_initial_assess = va_initial_assess,
            va_reviewer_initial_assess=va_reviewer_initial_assess,
            va_reviewer_final_assess=va_reviewer_final_assess,
            va_coder_review = va_coder_review,
            smartva = smartva,
            da_va_final_assess = da_va_final_assess,
            da_va_initial_assess = da_va_initial_assess,
            da_va_coder_review = da_va_coder_review,
            narrative_qa_enabled = narrative_qa_enabled,
            social_autopsy_enabled = social_autopsy_enabled,
            va_narrative_assessment = va_narrative_assessment,
            social_autopsy_analysis_questions = SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS,
            va_social_autopsy_analysis = va_social_autopsy_analysis,
            social_autopsy_selected_pairs = social_autopsy_selected_pairs,
            next_block_message = next_block_message,
            cod_attachments_data = cod_attachments_data,
            cod_attachments_labels = cod_attachments_labels,
            cod_attachments_render_modes = cod_attachments_render_modes,
            cod_health_history_data = cod_health_history_data,
            cod_health_history_labels = cod_health_history_labels,
            va_usernote = va_usernote,
        ))
        return _apply_partial_cache_policy(response, va_partial, va_action)
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
        form = VaInitialAssessmentForm()
        save_clicked = form.va_save_assessment.data
        not_codeable_clicked = form.va_not_codeable.data
        agelabels = {
            "isNeonatal": (va_payload_data or {}).get("isNeonatal"),
            "isChild": (va_payload_data or {}).get("isChild"),
            "isAdult": (va_payload_data or {}).get("isAdult"),
        }
        active_age_label = next(
            (k for k, v in agelabels.items() if str(v).strip() in ("1", "1.0")),
            None
        )
        if active_age_label == "isAdult":
            form.va_other_conditions.choices = adult
        elif active_age_label == "isChild":
            form.va_other_conditions.choices = children
        elif active_age_label == "isNeonate":
            form.va_other_conditions.choices = neonate
        else:
            form.va_other_conditions.choices = adult
        if save_clicked and form.validate_on_submit():
            coding_errors: list[tuple[object, str]] = []
            classifications = set()
            for field in (form.va_immediate_cod, form.va_antecedent_cod):
                try:
                    classifications.add(
                        validate_coding_value_for_submission(va_sid, field.data)
                    )
                except (LookupError, ValueError) as exc:
                    coding_errors.append((field, str(exc)))
            # One classification per save, even in a selectable project.
            if not coding_errors and len(classifications) > 1:
                coding_errors.append(
                    (
                        form.va_antecedent_cod,
                        "Immediate and antecedent causes must both be ICD-10 or both be ICD-11.",
                    )
                )
            initial_icd11_provenance = None
            if not coding_errors:
                try:
                    initial_icd11_provenance = build_icd11_provenance_for_values(
                        va_sid,
                        {
                            "immediate": form.va_immediate_cod.data,
                            "antecedent": form.va_antecedent_cod.data,
                        },
                    )
                except (LookupError, ValueError) as exc:
                    coding_errors.append((form.va_immediate_cod, str(exc)))
            if coding_errors:
                for field, message in coding_errors:
                    field.errors.append(message)
                return render_template(
                    f"va_form_partials/{va_partial}.html",
                    form=form,
                    va_action=va_action,
                    va_actiontype=va_actiontype,
                    va_sid=va_sid,
                    pre_immediate_cod=form.va_immediate_cod.data,
                    pre_antecedent_cod=form.va_antecedent_cod.data,
                )
            form1 = VaFinalAssessmentForm()
            smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
            for existing_initial in db.session.scalars(
                sa.select(VaInitialAssessments).where(
                    VaInitialAssessments.va_sid == va_sid,
                    VaInitialAssessments.va_iniassess_by == current_user.user_id,
                    VaInitialAssessments.va_iniassess_status == VaStatuses.active,
                )
            ).all():
                existing_initial.va_iniassess_status = VaStatuses.deactive
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=va_sid,
                        va_audit_byrole="vacoder",
                        va_audit_by=current_user.user_id,
                        va_audit_operation="d",
                        va_audit_action="superseded initial cod draft",
                        va_audit_entityid=existing_initial.va_iniassess_id,
                    )
                )
            gen_uuid = uuid.uuid4()
            new_review = VaInitialAssessments(
                va_iniassess_id=gen_uuid,
                va_sid=va_sid,
                va_iniassess_by=current_user.user_id,
                va_immediate_cod=form.va_immediate_cod.data,
                va_antecedent_cod=form.va_antecedent_cod.data,
                icd11_provenance=initial_icd11_provenance,
                va_other_conditions=" | ".join(form.va_other_conditions.data) if form.va_other_conditions.data else None,
                # va_rreview=form.va_rreview.data,
                # va_rreview_fail=form.va_rreview_fail.data.strip() or None,
                # va_rreview_remark=form.va_rreview_remark.data.strip() or None,
            )
            db.session.add(new_review)
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "initial cod submitted",
                    va_audit_entityid = gen_uuid
                )
            )
            current_state = get_submission_workflow_state(va_sid)
            session_timed_out = (current_state == WORKFLOW_READY_FOR_CODING)
            step1_resaved = (current_state == WORKFLOW_CODER_STEP1_SAVED)
            try:
                mark_coder_step1_saved(
                    va_sid,
                    reason="initial_cod_updated" if step1_resaved else "initial_cod_submitted",
                    actor=coder_actor(current_user.user_id),
                )
            except WorkflowTransitionError:
                log.warning(
                    "coder_step1_saved blocked | sid=%s | current_state=%r"
                    " | coder_user_id=%s",
                    va_sid,
                    current_state,
                    current_user.user_id,
                )
                raise
            db.session.commit()
            va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
            return render_template("va_form_partials/vafinalasses.html", form = form1, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, smartva=smartva, va_immediate_cod = va_initial_assess.va_immediate_cod or None, va_antecedent_cod = va_initial_assess.va_antecedent_cod or None, va_other_conditions = va_initial_assess.va_other_conditions or None, session_timed_out=session_timed_out, step1_resaved=step1_resaved)
        elif not_codeable_clicked:
            form2 = VaCoderReviewForm()
            return render_template("va_form_partials/vacoderreview.html", form = form2, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid)
        # GET — pre-populate from any existing active initial assessment
        existing_assess = db.session.scalar(
            sa.select(VaInitialAssessments)
            .where(
                VaInitialAssessments.va_sid == va_sid,
                VaInitialAssessments.va_iniassess_by == current_user.user_id,
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            )
            .order_by(VaInitialAssessments.va_iniassess_createdat.desc())
        )
        # Recode resume fallback:
        # After final COD submission, the active initial draft is intentionally
        # deactivated. When a fresh recode session starts, prefill Step 1 from
        # the coder's latest prior initial draft if no active draft exists.
        if (
            existing_assess is None
            and va_action == "vacode"
            and va_actiontype == "varesumecoding"
            and get_active_recode_episode(va_sid)
        ):
            existing_assess = db.session.scalar(
                sa.select(VaInitialAssessments)
                .where(
                    VaInitialAssessments.va_sid == va_sid,
                    VaInitialAssessments.va_iniassess_by == current_user.user_id,
                )
                .order_by(VaInitialAssessments.va_iniassess_createdat.desc())
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
        return render_template(
            f"va_form_partials/{va_partial}.html",
            form=form,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            pre_immediate_cod=pre_immediate_cod,
            pre_antecedent_cod=pre_antecedent_cod,
        )
    if va_partial == "vafinalasses":
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
                pre_conclusive_cod=(
                    prior_authoritative_final.va_conclusive_cod
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
                form_error_messages=error_messages or [],
            )

        if form1.validate_on_submit():
            blocking_messages: list[str] = []
            try:
                validate_coding_value_for_submission(
                    va_sid,
                    form1.va_conclusive_cod.data,
                )
            except (LookupError, ValueError) as exc:
                blocking_messages.append(str(exc))

            # Enforce NQA completion if enabled for this project
            _project = _get_project_for_submission(va_sid)
            if _project and _project.narrative_qa_enabled:
                _nqa_done = get_current_payload_narrative_assessment(
                    va_sid,
                    current_user.user_id,
                )
                if not _nqa_done:
                    blocking_messages.append(
                        "Narrative Quality Assessment must be completed before submitting the final COD."
                    )
            _submission = db.session.get(VaSubmissions, va_sid)
            _sub_active_version = get_active_payload_version(va_sid) if _submission else None
            _sub_payload_data = _sub_active_version.payload_data if _sub_active_version else None
            _form_type_code = va_get_form_type_code_for_form(
                _submission.va_form_id if _submission else None
            )
            _visible_category_codes = get_visible_category_codes(
                _sub_payload_data,
                _submission.va_form_id if _submission else None,
            )
            _category_service = get_category_rendering_service()
            if (
                _is_social_autopsy_enabled_for_submission(va_sid, va_action)
                and _category_service.is_category_enabled(
                _form_type_code,
                "vacode",
                _visible_category_codes,
                "social_autopsy",
                )
            ):
                _social_done = get_current_payload_social_autopsy_analysis(
                    va_sid,
                    current_user.user_id,
                )
                if not _social_done:
                    blocking_messages.append(
                        "Social Autopsy Analysis must be completed before submitting the final COD."
                    )
            final_icd11_provenance = None
            if not blocking_messages:
                try:
                    final_icd11_provenance = build_icd11_provenance_for_values(
                        va_sid,
                        {"conclusive": form1.va_conclusive_cod.data},
                    )
                except (LookupError, ValueError) as exc:
                    blocking_messages.append(str(exc))
            if blocking_messages:
                if request.headers.get("HX-Request"):
                    return _render_final_assessment_form(blocking_messages)
                for message in blocking_messages:
                    flash(message, "warning")
                return redirect(request.referrer or url_for("coding.dashboard"))
            gen_uuid = uuid.uuid4()
            submission = db.session.get(VaSubmissions, va_sid)
            active_payload_version = get_active_payload_version(va_sid)
            if active_payload_version is None:
                raise ValueError(f"Submission {va_sid} has no active payload version.")
            active_recode_episode = get_active_recode_episode(va_sid)
            prior_authoritative_final = get_authoritative_final_assessment(va_sid)
            existing_active_finals = db.session.scalars(
                sa.select(VaFinalAssessments).where(
                    VaFinalAssessments.va_sid == va_sid,
                    VaFinalAssessments.payload_version_id
                    == active_payload_version.payload_version_id,
                    VaFinalAssessments.va_finassess_status == VaStatuses.active,
                )
            ).all()
            new_review1 = VaFinalAssessments(
                va_finassess_id=gen_uuid,
                va_sid=va_sid,
                payload_version_id=active_payload_version.payload_version_id,
                va_finassess_by=current_user.user_id,
                source_initial_assessment_id=(
                    va_initial_assess.va_iniassess_id if va_initial_assess else None
                ),
                va_conclusive_cod=form1.va_conclusive_cod.data,
                icd11_provenance=final_icd11_provenance,
                va_finassess_remark=form1.va_finassess_remark.data.strip() or None,
                demo_expires_at=_demo_expiry_for_actiontype(va_sid, va_actiontype),
                # va_rreview=form.va_rreview.data,
                # va_rreview_fail=form.va_rreview_fail.data.strip() or None,
                # va_rreview_remark=form.va_rreview_remark.data.strip() or None,
            )
            db.session.add(new_review1)

            for existing_final in existing_active_finals:
                existing_final.va_finassess_status = VaStatuses.deactive
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=va_sid,
                        va_audit_byrole="vacoder",
                        va_audit_by=current_user.user_id,
                        va_audit_operation="d",
                        va_audit_action=(
                            "superseded authoritative final cod"
                            if prior_authoritative_final
                            and existing_final.va_finassess_id
                            == prior_authoritative_final.va_finassess_id
                            else "deactivated superseded final cod"
                        ),
                        va_audit_entityid=existing_final.va_finassess_id,
                    )
                )

            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "final cod submitted",
                    va_audit_entityid = gen_uuid
                )
            )
            va_has_allocation = db.session.scalar(
                sa.select(VaAllocations).where(
                    VaAllocations.va_sid == va_sid,
                    VaAllocations.va_allocated_to == current_user.user_id,
                    VaAllocations.va_allocation_for == VaAllocation.coding,
                    VaAllocations.va_allocation_status == VaStatuses.active,
                )
            )
            va_has_allocation.va_allocation_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "d",
                    va_audit_action = "allocated form released from coder",
                    va_audit_entityid = va_has_allocation.va_allocation_id
                )
            )
            db.session.flush()
            upsert_final_cod_authority(
                va_sid,
                new_review1,
                reason=(
                    "replacement_final_cod_submitted"
                    if active_recode_episode
                    else "final_cod_submitted"
                ),
                source_role="vacoder",
                updated_by=current_user.user_id,
            )
            if active_recode_episode:
                mark_recode_finalized(
                    va_sid,
                    reason="replacement_final_cod_submitted",
                    actor=coder_actor(current_user.user_id),
                )
                complete_recode_episode(active_recode_episode, new_review1)
            else:
                mark_coder_finalized(
                    va_sid,
                    reason="final_cod_submitted",
                    actor=coder_actor(current_user.user_id),
                )
            db.session.commit()
            bust_coder_dashboard_cache(current_user.user_id)
            # The conclusive COD is stored: attach the picked code to the
            # search the browser says produced it (digitva-zpe.3). Runs after
            # the save committed; a telemetry failure cannot unsave the COD.
            coding_search_telemetry_service.record_choice(
                search_id=request.form.get("cod_search_id"),
                chosen_code=request.form.get("cod_chosen_code"),
                chosen_rank=request.form.get("cod_chosen_rank"),
                role=coding_search_telemetry_service.role_label(current_user),
            )
            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = url_for('coding.dashboard')
                flash("VA Coding submitted successfully!", "success")
                return response
        return _render_final_assessment_form()
    if va_partial == "vausernote":
        form = VaUsernoteForm()
        va_usernote = db.session.scalar(
            sa.select(VaUsernotes).where(
                VaUsernotes.note_by == current_user.user_id,
                VaUsernotes.note_vasubmission == va_sid,
                VaUsernotes.note_status == VaStatuses.active,
            )
        )
        if form.validate_on_submit():
            if va_usernote:
                va_usernote.note_content = form.va_note_content.data
            else:
                new_note = VaUsernotes(
                    note_by=current_user.user_id,
                    note_vasubmission=va_sid,
                    note_content=form.va_note_content.data
                )
                db.session.add(new_note)
            db.session.commit()
            obb_response = render_template("va_intermediate_partials/va_note_notification.html", message="Note Saved!")
            main_response = render_template(f"va_form_partials/{va_partial}.html", va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, form=form)
            return obb_response + main_response
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
        if form.validate_on_submit():
            gen_uuid = uuid.uuid4()
            other_reason = form.va_creview_other.data.strip() or None
            new_coder_review = VaCoderReview(
                va_creview_id = gen_uuid,
                va_sid = va_sid,
                va_creview_by = current_user.user_id,
                va_creview_reason = form.va_creview_reason.data,
                va_creview_other = other_reason
            )
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "c",
                    va_audit_action = "error reported by coder",
                    va_audit_entityid = gen_uuid
                )
            )
            va_has_allocation = db.session.scalar(
                sa.select(VaAllocations).where(
                    VaAllocations.va_sid == va_sid,
                    VaAllocations.va_allocated_to == current_user.user_id,
                    VaAllocations.va_allocation_for == VaAllocation.coding,
                    VaAllocations.va_allocation_status == VaStatuses.active,
                )
            )
            va_has_allocation.va_allocation_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid = va_sid,
                    va_audit_byrole = "vacoder",
                    va_audit_by = current_user.user_id,
                    va_audit_operation = "d",
                    va_audit_action = "allocated form released from coder",
                    va_audit_entityid = va_has_allocation.va_allocation_id
                )
            )
            db.session.add(new_coder_review)
            mark_coder_not_codeable(
                va_sid,
                reason="coder_marked_not_codeable",
                actor=coder_actor(current_user.user_id),
            )
            odk_sync_result = sync_not_codeable_review_state(
                va_sid,
                form.va_creview_reason.data,
                other_reason,
            )
            if odk_sync_result.success:
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=va_sid,
                        va_audit_byrole="vacoder",
                        va_audit_by=current_user.user_id,
                        va_audit_operation="u",
                        va_audit_action=f"odk review state set to {odk_sync_result.review_state}",
                    )
                )
            else:
                db.session.add(
                    VaSubmissionsAuditlog(
                        va_sid=va_sid,
                        va_audit_byrole="vacoder",
                        va_audit_by=current_user.user_id,
                        va_audit_operation="u",
                        va_audit_action="odk review state update failed",
                    )
                )
            db.session.commit()
            success_message = "Not Codeable saved locally."
            warning_message = None
            if odk_sync_result.success:
                success_message += " ODK Central was flagged for revision."
            else:
                warning_message = (
                    "Not Codeable was saved locally, but ODK Central could not be "
                    f"updated automatically. {odk_sync_result.error_message}"
                )
            flash(success_message, "success")
            if warning_message:
                flash(warning_message, "warning")
            bust_coder_dashboard_cache(current_user.user_id)
            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = url_for('coding.dashboard')
                return response
        return _render_coder_review_form()
    abort(404)




@va_form.route('/attachment/<path:storage_name_raw>')
@role_required("coder", "reviewer", "data_manager", "site_pi", "project_pi", "admin")
def serve_attachment(storage_name_raw):
    """Serve an attachment by opaque storage_name token.

    Security contract (docs/policy/attachment-storage.md):
      1. @role_required handles auth + active-status + role gate
      2. Format validation → 404
      3. Record lookup (exists_on_odk=True only) → 404
      4. Submission-level authorization for the current user → 403
      5. Delivery (local or Central-backed, no-store) → 200 / 404 / 502 / 503

    Everything after the format check is delegated to the attachment service;
    this route learns nothing about where the bytes live.
    """
    if not re.match(r'^[a-f0-9]{32}\.[a-z0-9]{1,5}$', storage_name_raw):
        abort(404)

    record = attachment_service.resolve_attachment_record(storage_name_raw)
    if record is None:
        abort(404)

    if not attachment_service.can_access_submission_attachment(
        current_user, va_form_id=record.va_form_id, va_sid=record.va_sid
    ):
        log.warning(
            "serve_attachment: user=%s denied access to sid=%s form=%s",
            current_user.user_id, record.va_sid, record.va_form_id,
        )
        abort(403)

    return attachment_service.deliver(record)


@va_form.route('/media/<va_form_id>/<va_filename>')
@login_required
def serve_media(va_form_id, va_filename):
    # DEPRECATED: use /attachment/<storage_name> for new attachments.
    # Kept for backward compatibility during migration (storage_name IS NULL rows).
    log.info("serve_media legacy hit: form=%s file=%s", va_form_id, va_filename)

    # Validate form_id format to prevent path traversal
    if not va_form_id or not re.match(r'^[A-Za-z0-9_-]+$', va_form_id):
        abort(400, description="Invalid form ID format")

    # Ownership must resolve before any authorization decision (the previous
    # missing-record branch skipped the allocation check entirely).
    att_row = db.session.execute(
        sa.select(
            VaSubmissionAttachments.va_sid,
            VaSubmissionAttachments.storage_name,
            VaSubmissionAttachments.local_path,
            VaSubmissionAttachments.mime_type,
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
        .where(
            VaSubmissions.va_form_id == va_form_id,
            VaSubmissionAttachments.filename == va_filename,
        )
    ).first()
    if att_row is None:
        abort(404)
    att_sid = att_row.va_sid

    # Same role matrix as /attachment; evaluated fresh, never cached.
    if not attachment_service.can_access_submission_attachment(
        current_user, va_form_id=va_form_id, va_sid=att_sid
    ):
        log.warning(
            "serve_media: user=%s denied access to %s/%s (sid=%s)",
            current_user.user_id, va_form_id, va_filename, att_sid,
        )
        va_permission_abortwithflash(f"You don't have permissions to access the media files for '{va_form_id}'", 403)

    # Sanitize filename to prevent path traversal attacks
    safe_filename = secure_filename(va_filename)
    if not safe_filename:
        abort(400, description="Invalid filename")

    # Additional check for path traversal patterns
    if '..' in va_filename or va_filename.startswith('/') or va_filename.startswith('\\'):
        abort(400, description="Invalid filename")

    # Same store as /attachment. A legacy row has no storage_name, so the
    # sanitized ODK filename is the object name under the form's media
    # directory — exactly what this route used to send directly. With the S3
    # store such a row has no object and the result is a 404, not a presign.
    record = attachment_service.AttachmentRecord(
        va_sid=att_sid,
        va_form_id=va_form_id,
        storage_name=att_row.storage_name or safe_filename,
        filename=va_filename,
        local_path=att_row.local_path,
        mime_type=att_row.mime_type,
    )
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


def _get_required_completion_block(va_sid: str, va_partial: str, va_action: str, va_actiontype: str):
    """Return a blocking message if the current category has an incomplete required form."""
    if va_action not in {"vacode", "vareview"}:
        return None
    if va_actiontype not in {
        "vastartcoding",
        "vapickcoding",
        "varesumecoding",
        "vademo_start_coding",
        "vastartreviewing",
        "varesumereviewing",
    }:
        return None

    if va_partial == "social_autopsy" and _is_social_autopsy_enabled_for_submission(va_sid, va_action):
        analysis = get_current_payload_social_autopsy_analysis(
            va_sid,
            current_user.user_id,
        )
        if not analysis:
            return "Save the Social Autopsy Analysis before proceeding to the next category."

    if va_partial == "vanarrationanddocuments":
        project = _get_project_for_submission(va_sid)
        if project and project.narrative_qa_enabled:
            nqa = get_current_payload_narrative_assessment(
                va_sid,
                current_user.user_id,
            )
            if not nqa:
                return "Complete the Narrative Quality Assessment before proceeding."

    return None
