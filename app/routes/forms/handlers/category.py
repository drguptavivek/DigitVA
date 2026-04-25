import uuid

from flask import flash, make_response, render_template, request
from flask_login import current_user
import sqlalchemy as sa

from app import cache as flask_cache, db
from app.forms import VaDataManagerReviewForm
from app.models import (
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionsAuditlog,
    VaUsernotes,
)
import app.routes.forms as form_routes
from app.services.forms.category_rendering import get_visible_category_codes
from app.services.forms.field_mapping import get_mapping_service
from app.services.coding.final_cod_authority import (
    get_authoritative_final_cod_record,
)
from app.services.assessments.payload_artifacts import (
    get_current_payload_narrative_assessment,
    get_current_payload_reviewer_review,
    get_current_payload_social_autopsy_analysis,
)
from app.services.forms.social_autopsy import SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS
from app.services.submissions.summary import build_submission_summary
from app.services.workflow.definition import (
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    sync_submission_workflow_from_legacy_records,
)
from app.services.workflow.transitions import data_manager_actor, mark_data_manager_not_codeable
from app.utils import (
    va_get_form_type_code_for_form,
    va_render_processcategorydata,
)
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel

from ..helpers import (
    DATA_MANAGER_TRIAGE_ALLOWED_STATES,
    _apply_partial_cache_policy,
    _data_manager_reason_label,
    _get_display_initial_assessment,
    _get_required_completion_block,
    _is_social_autopsy_enabled_for_submission,
    _section_data_cache_key,
    _SECTION_CACHE_TIMEOUT,
)


def handle_category_partial(va_sid, va_partial, va_action, va_actiontype, va_submission, va_payload_data):
    _form_type_code = va_get_form_type_code_for_form(
        va_submission.va_form_id if va_submission else None
    )
    visible_category_codes = get_visible_category_codes(
        va_payload_data,
        va_submission.va_form_id if va_submission else None,
    )
    category_service = form_routes.get_category_rendering_service()
    if not category_service.is_category_enabled(
        _form_type_code,
        va_action,
        visible_category_codes,
        va_partial,
    ):
        return None

    if va_partial == "vadmtriage":
        return _handle_dm_triage(
            va_sid,
            va_partial,
            va_action,
            va_actiontype,
            _form_type_code,
            visible_category_codes,
            category_service,
        )

    _mapping_svc = get_mapping_service()
    category_config = category_service.get_category_config(
        _form_type_code,
        va_action,
        va_partial,
    )
    va_mapping_choice = _mapping_svc.get_choices(_form_type_code)
    va_mapping_flip = _mapping_svc.get_flip_labels(_form_type_code)
    va_mapping_info = _mapping_svc.get_info_labels(_form_type_code)
    subcategory_labels = _mapping_svc.get_subcategory_labels(_form_type_code, va_partial)
    subcategory_render_modes = _mapping_svc.get_subcategory_render_modes(
        _form_type_code,
        va_partial,
    )
    _data_cache_key = _section_data_cache_key(va_sid, va_partial)
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
        summary_items = build_submission_summary(_form_type_code, va_payload_data)
        va_datalevel = va_get_render_datalevel(
            va_action,
            _form_type_code,
            visible_category_codes,
        )
        va_processedcategorydata = va_render_processcategorydata(
            va_payload_data,
            va_submission.va_form_id,
            va_datalevel,
            va_mapping_choice,
            va_partial,
            va_sid=va_submission.va_sid,
        )
        cod_attachments_data = {}
        cod_attachments_labels = {}
        cod_attachments_render_modes = {}
        cod_health_history_data = {}
        cod_health_history_labels = {}
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
        smartva = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                (VaSmartvaResults.va_sid == va_sid)
                & (VaSmartvaResults.va_smartva_status == VaStatuses.active)
            )
        )
        flask_cache.set(
            _data_cache_key,
            {
                "summary_items": summary_items,
                "va_processedcategorydata": va_processedcategorydata,
                "cod_attachments_data": cod_attachments_data,
                "cod_attachments_labels": cod_attachments_labels,
                "cod_attachments_render_modes": cod_attachments_render_modes,
                "cod_health_history_data": cod_health_history_data,
                "cod_health_history_labels": cod_health_history_labels,
                "smartva": smartva,
            },
            timeout=_SECTION_CACHE_TIMEOUT,
        )

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
        reviewobject = get_current_payload_reviewer_review(va_sid, current_user.user_id)
    elif va_action == "vacode":
        reviewobject = db.session.scalar(
            sa.select(VaReviewerReview).where(
                (VaReviewerReview.va_rreview_status == VaStatuses.active)
                & (VaReviewerReview.va_sid == va_sid)
            )
        )
    authoritative_final_assess = get_authoritative_final_cod_record(va_sid)
    vafinexists = authoritative_final_assess.va_sid if authoritative_final_assess else None
    vaerrexists = db.session.scalar(
        sa.select(VaCoderReview.va_sid).where(
            (VaCoderReview.va_creview_status == VaStatuses.active)
            & (VaCoderReview.va_sid == va_sid)
        )
    )
    _ini_filter = [
        VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        VaInitialAssessments.va_sid == va_sid,
    ]
    if va_action == "vacode":
        _ini_filter.append(VaInitialAssessments.va_iniassess_by == current_user.user_id)
    vainiexists = db.session.scalar(sa.select(VaInitialAssessments.va_sid).where(*_ini_filter))
    va_final_assess = authoritative_final_assess
    va_initial_assess = _get_display_initial_assessment(va_sid)
    va_coder_review = db.session.scalar(
        sa.select(VaCoderReview).where(
            (VaCoderReview.va_creview_status == VaStatuses.active)
            & (VaCoderReview.va_sid == va_sid)
        )
    )
    da_va_final_assess = db.session.scalar(
        sa.select(VaFinalAssessments).where(
            (VaFinalAssessments.va_finassess_status == VaStatuses.deactive)
            & (VaFinalAssessments.va_sid == va_sid)
            & (VaFinalAssessments.va_finassess_by == current_user.user_id)
        )
    )
    da_va_initial_assess = None
    da_va_coder_review = db.session.scalar(
        sa.select(VaCoderReview).where(
            (VaCoderReview.va_creview_status == VaStatuses.deactive)
            & (VaCoderReview.va_sid == va_sid)
            & (VaCoderReview.va_creview_by == current_user.user_id)
        )
    )
    _nqa_project = None
    if va_partial == "vanarrationanddocuments":
        from app.services.projects.submission_lookup import get_project_for_submission

        _nqa_project = get_project_for_submission(va_sid)
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
    response = make_response(
        render_template(
            template_name,
            instance_name=va_submission.va_uniqueid_masked,
            category_data=va_processedcategorydata,
            category_config=category_config,
            subcategory_labels=subcategory_labels,
            subcategory_render_modes=subcategory_render_modes,
            va_previouscategory=va_previouscategory,
            va_nextcategory=va_nextcategory,
            flip_list=va_mapping_flip,
            info_list=va_mapping_info,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            va_partial=va_partial,
            summary=va_submission.va_summary,
            summary_items=summary_items,
            reviewobject=reviewobject,
            vafinexists=vafinexists,
            vaerrexists=vaerrexists,
            vainiexists=vainiexists,
            va_final_assess=va_final_assess,
            va_initial_assess=va_initial_assess,
            va_coder_review=va_coder_review,
            smartva=smartva,
            da_va_final_assess=da_va_final_assess,
            da_va_initial_assess=da_va_initial_assess,
            da_va_coder_review=da_va_coder_review,
            narrative_qa_enabled=narrative_qa_enabled,
            social_autopsy_enabled=social_autopsy_enabled,
            va_narrative_assessment=va_narrative_assessment,
            social_autopsy_analysis_questions=SOCIAL_AUTOPSY_ANALYSIS_QUESTIONS,
            va_social_autopsy_analysis=va_social_autopsy_analysis,
            social_autopsy_selected_pairs=social_autopsy_selected_pairs,
            next_block_message=next_block_message,
            cod_attachments_data=cod_attachments_data,
            cod_attachments_labels=cod_attachments_labels,
            cod_attachments_render_modes=cod_attachments_render_modes,
            cod_health_history_data=cod_health_history_data,
            cod_health_history_labels=cod_health_history_labels,
            va_usernote=va_usernote,
        )
    )
    return _apply_partial_cache_policy(response, va_partial, va_action)


def _handle_dm_triage(
    va_sid,
    va_partial,
    va_action,
    va_actiontype,
    form_type_code,
    visible_category_codes,
    category_service,
):
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
        if submission_workflow not in DATA_MANAGER_TRIAGE_ALLOWED_STATES:
            return render_template(
                "va_formcategory_partials/category_data_manager_triage.html",
                category_config=category_service.get_category_config(
                    form_type_code,
                    va_action,
                    va_partial,
                ),
                va_action=va_action,
                va_actiontype=va_actiontype,
                va_sid=va_sid,
                va_partial=va_partial,
                form=form,
                va_previouscategory=category_service.get_category_neighbours(
                    form_type_code,
                    va_action,
                    visible_category_codes,
                    va_partial,
                )[0],
                va_nextcategory=category_service.get_category_neighbours(
                    form_type_code,
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
            odk_sync_result = form_routes.sync_not_codeable_review_state(
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
        form_type_code,
        va_action,
        visible_category_codes,
        va_partial,
    )
    return render_template(
        "va_formcategory_partials/category_data_manager_triage.html",
        category_config=category_service.get_category_config(
            form_type_code,
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
