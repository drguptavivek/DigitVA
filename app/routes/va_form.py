import logging
import os
import re
import uuid

log = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaSubmissionWorkflow, VaSubmissionWorkflowEvent, VaReviewerReview, VaAllocations, VaAllocation, VaStatuses, VaFinalAssessments, VaInitialAssessments, VaCoderReview, VaDataManagerReview, VaSmartvaResults, VaUsernotes, VaSubmissionsAuditlog
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.decorators import va_validate_permissions
from flask_login import current_user, login_required
from flask import Blueprint, render_template, current_app, send_file, send_from_directory, flash, redirect, url_for, jsonify, request, abort
from werkzeug.utils import secure_filename
from app.utils import va_get_form_type_code_for_form, va_render_processcategorydata, va_permission_abortwithflash
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel
from app.services.category_rendering_service import (
    get_category_rendering_service,
    get_visible_category_codes,
)
from app.services.final_cod_authority_service import (
    complete_recode_episode,
    get_active_recode_episode,
    get_authoritative_final_cod_record,
    get_authoritative_final_assessment,
    upsert_final_cod_authority,
)
from app.services.submission_payload_version_service import ensure_active_payload_version, get_active_payload_version
from app.services.field_mapping_service import get_mapping_service
from app.services.coding_service import get_project_for_submission as _get_project_for_submission
from app.services.payload_bound_coding_artifact_service import (
    deactivate_other_active_reviewer_reviews,
    get_current_payload_narrative_assessment,
    get_current_payload_reviewer_review,
    get_current_payload_social_autopsy_analysis,
    get_submission_with_current_payload,
)
from app.services.social_autopsy_analysis_service import SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
from app.services.submission_summary_service import build_submission_summary
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_SCREENING_PENDING,
)
from app.services.workflow.transitions import (
    coder_actor,
    data_manager_actor,
    mark_coder_finalized,
    mark_coder_not_codeable,
    mark_coder_step1_saved,
    mark_data_manager_not_codeable,
    mark_recode_finalized,
)
from app.services.odk_review_service import sync_not_codeable_review_state
from app.services.demo_project_service import get_demo_expiry_for_submission
from app.forms import VaReviewerReviewForm, VaInitialAssessmentForm, VaCoderReviewForm, VaDataManagerReviewForm, VaFinalAssessmentForm, VaUsernoteForm


va_form = Blueprint("va_form", __name__)
def _demo_expiry_for_actiontype(va_sid: str, va_actiontype: str):
    """Return the demo artifact expiry timestamp for demo coding saves."""
    return get_demo_expiry_for_submission(va_sid, va_actiontype)


def _is_social_autopsy_enabled_for_submission(va_sid: str) -> bool:
    """Return whether the app-owned Social Autopsy analysis form is enabled."""
    project = _get_project_for_submission(va_sid)
    if project is None:
        return True
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
            submission_workflow = db.session.scalar(
                sa.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == va_sid
                )
            )
            success_message = None

            if request.method == "POST":
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
        summary_items = build_submission_summary(
            _form_type_code,
            va_payload_data,
        )

        va_datalevel = va_get_render_datalevel(
            va_action,
            _form_type_code,
            visible_category_codes,
        )
        va_processedcategorydata = va_render_processcategorydata(va_payload_data, va_submission.va_form_id, va_datalevel, va_mapping_choice, va_partial, va_sid=va_submission.va_sid)
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
        vainiexists = db.session.scalar(sa.select(VaInitialAssessments.va_sid).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
        va_final_assess = authoritative_final_assess
        va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
        va_coder_review = db.session.scalar(sa.select(VaCoderReview).where((VaCoderReview.va_creview_status == VaStatuses.active)&(VaCoderReview.va_sid == va_sid)))
        smartva = db.session.scalar(sa.select(VaSmartvaResults).where((VaSmartvaResults.va_sid == va_sid)&(VaSmartvaResults.va_smartva_status == VaStatuses.active)))
        da_va_final_assess = db.session.scalar(sa.select(VaFinalAssessments).where((VaFinalAssessments.va_finassess_status == VaStatuses.deactive)&(VaFinalAssessments.va_sid == va_sid)&(VaFinalAssessments.va_finassess_by == current_user.user_id)))
        da_va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.deactive)&(VaInitialAssessments.va_sid == va_sid)&(VaInitialAssessments.va_iniassess_by == current_user.user_id)))
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
        # NQA context (only relevant for vanarrationanddocuments + vacode)
        _nqa_project = _get_project_for_submission(va_sid) if va_partial == "vanarrationanddocuments" else None
        narrative_qa_enabled = bool(_nqa_project and _nqa_project.narrative_qa_enabled)
        social_autopsy_enabled = (
            _is_social_autopsy_enabled_for_submission(va_sid)
            if va_partial == "social_autopsy"
            else False
        )
        va_narrative_assessment = None
        if narrative_qa_enabled and va_action == "vacode":
            va_narrative_assessment = get_current_payload_narrative_assessment(
                va_sid,
                current_user.user_id,
            )
        va_social_autopsy_analysis = None
        cod_attachments_data = {}
        cod_attachments_labels = {}
        cod_attachments_render_modes = {}
        cod_health_history_data = {}
        cod_health_history_labels = {}
        va_usernote = db.session.scalar(
            sa.select(VaUsernotes).where(
                VaUsernotes.note_by == current_user.user_id,
                VaUsernotes.note_vasubmission == va_sid,
                VaUsernotes.note_status == VaStatuses.active,
            )
        )
        if va_partial == "social_autopsy" and va_action == "vacode" and social_autopsy_enabled:
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
        if category_config and category_config.render_mode == "workflow_panel":
            cod_attachments_data = va_render_processcategorydata(
                va_payload_data,
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
                va_payload_data,
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
        return render_template(
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
        )
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
            mark_coder_step1_saved(
                va_sid,
                reason="initial_cod_submitted",
                actor=coder_actor(current_user.user_id),
            )
            db.session.commit()
            va_initial_assess = db.session.scalar(sa.select(VaInitialAssessments).where((VaInitialAssessments.va_iniassess_status == VaStatuses.active)&(VaInitialAssessments.va_sid == va_sid)))
            return render_template("va_form_partials/vafinalasses.html", form = form1, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid, smartva=smartva, va_immediate_cod = va_initial_assess.va_immediate_cod or None, va_antecedent_cod = va_initial_assess.va_antecedent_cod or None, va_other_conditions = va_initial_assess.va_other_conditions or None)
        elif not_codeable_clicked:
            form2 = VaCoderReviewForm()
            return render_template("va_form_partials/vacoderreview.html", form = form2, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid)
        return render_template(
            f"va_form_partials/{va_partial}.html", form = form, va_action = va_action, va_actiontype= va_actiontype, va_sid = va_sid,
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

        def _render_final_assessment_form(error_messages=None):
            return render_template(
                f"va_form_partials/{va_partial}.html",
                form=form1,
                va_action=va_action,
                va_actiontype=va_actiontype,
                va_sid=va_sid,
                smartva=smartva,
                va_immediate_cod=va_initial_assess.va_immediate_cod or None,
                va_antecedent_cod=va_initial_assess.va_antecedent_cod or None,
                va_other_conditions=va_initial_assess.va_other_conditions or None,
                form_error_messages=error_messages or [],
            )

        if form1.validate_on_submit():
            blocking_messages: list[str] = []

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
                _is_social_autopsy_enabled_for_submission(va_sid)
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
                va_conclusive_cod=form1.va_conclusive_cod.data,
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
                complete_recode_episode(active_recode_episode, new_review1)
                mark_recode_finalized(
                    va_sid,
                    reason="replacement_final_cod_submitted",
                    actor=coder_actor(current_user.user_id),
                )
            else:
                mark_coder_finalized(
                    va_sid,
                    reason="final_cod_submitted",
                    actor=coder_actor(current_user.user_id),
                )
            db.session.commit()
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
            if request.headers.get("HX-Request"):
                response = jsonify(success=True)
                response.headers["HX-Redirect"] = url_for('coding.dashboard')
                return response
        return _render_coder_review_form()
        
        
        

@va_form.route('/attachment/<path:storage_name_raw>')
def serve_attachment(storage_name_raw):
    """Serve an attachment by opaque storage_name token.

    Security contract (Option B — auth-first):
      1. Hard 401 for unauthenticated requests (no DB lookup)
      2. Format validation → 404
      3. DB lookup (exists_on_odk=True only) → 404
      4. Permission check → 403
      5. Path guard → 404
      6. File existence → 404
      7. Serve file
    """
    from app import cache as flask_cache

    if not current_user.is_authenticated:
        abort(401)

    if not re.match(r'^[a-f0-9]{32}\.[a-z0-9]{1,5}$', storage_name_raw):
        abort(404)

    storage_name = storage_name_raw

    # Cache lookup
    cached = flask_cache.get(f"att:{storage_name}")
    if cached:
        local_path = cached["local_path"]
        mime_type = cached["mime_type"]
        va_form_id = cached["va_form_id"]
    else:
        # DB fallback
        row = db.session.execute(
            sa.select(
                VaSubmissionAttachments.local_path,
                VaSubmissionAttachments.mime_type,
                VaSubmissions.va_form_id,
            )
            .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionAttachments.va_sid)
            .where(VaSubmissionAttachments.storage_name == storage_name)
            .where(VaSubmissionAttachments.exists_on_odk == True)  # noqa: E712
        ).first()
        if not row:
            abort(404)
        local_path, mime_type, va_form_id = row

    # Permission check
    if not current_user.has_va_form_access(va_form_id):
        abort(403)

    # Path guard — ensure local_path stays under APP_DATA/{va_form_id}/media/
    media_base = os.path.realpath(
        os.path.join(current_app.config["APP_DATA"], va_form_id, "media")
    )
    resolved = os.path.realpath(local_path)
    if not resolved.startswith(media_base + os.sep) and resolved != media_base:
        abort(404)

    # File existence check
    if not os.path.isfile(resolved):
        flask_cache.delete(f"att:{storage_name}")
        abort(404)

    # Write cache after all checks pass (only for rows we verified exist_on_odk=True)
    if not cached:
        flask_cache.set(f"att:{storage_name}", {
            "local_path": local_path,
            "mime_type": mime_type,
            "va_form_id": va_form_id,
        }, timeout=3600)

    return send_file(resolved, mimetype=mime_type)


@va_form.route('/media/<va_form_id>/<va_filename>')
@login_required
def serve_media(va_form_id, va_filename):
    # DEPRECATED: use /attachment/<storage_name> for new attachments.
    # Kept for backward compatibility during migration (storage_name IS NULL rows).
    log.info("serve_media legacy hit: form=%s file=%s", va_form_id, va_filename)

    # Validate form_id format to prevent path traversal
    if not va_form_id or not re.match(r'^[A-Za-z0-9_-]+$', va_form_id):
        abort(400, description="Invalid form ID format")

    if not current_user.has_va_form_access(va_form_id):
        va_permission_abortwithflash(f"You don't have permissions to access the media files for '{va_form_id}'", 403)

    # Sanitize filename to prevent path traversal attacks
    safe_filename = secure_filename(va_filename)
    if not safe_filename:
        abort(400, description="Invalid filename")

    # Additional check for path traversal patterns
    if '..' in va_filename or va_filename.startswith('/') or va_filename.startswith('\\'):
        abort(400, description="Invalid filename")

    media_base = os.path.join(
        current_app.config["APP_DATA"], va_form_id, "media"
    )
    return send_from_directory(media_base, safe_filename)





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
    if va_action != "vacode":
        return None
    if va_actiontype not in {"vastartcoding", "vapickcoding", "varesumecoding", "vademo_start_coding"}:
        return None

    if va_partial == "social_autopsy" and _is_social_autopsy_enabled_for_submission(va_sid):
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
