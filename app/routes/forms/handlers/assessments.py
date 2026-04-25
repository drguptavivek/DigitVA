import logging
import uuid

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
import sqlalchemy as sa

from app import db
from app.forms import (
    VaCoderReviewForm,
    VaFinalAssessmentForm,
    VaInitialAssessmentForm,
    VaReviewerReviewForm,
    VaUsernoteForm,
)
from app.models import (
    VaAllocations,
    VaAllocation,
    VaCoderReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflowEvent,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsernotes,
)
import app.routes.forms as form_routes
from app.services.coding.authority.final_cod import (
    complete_recode_episode,
    get_active_recode_episode,
    get_authoritative_final_assessment,
    upsert_final_cod_authority,
)
from app.services.coding.payload_artifacts import (
    deactivate_other_active_reviewer_reviews,
    get_current_payload_narrative_assessment,
    get_current_payload_social_autopsy_analysis,
    get_submission_with_current_payload,
)
from app.services.submissions.payload_version import get_active_payload_version
from app.services.workflow.definition import (
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_READY_FOR_CODING,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    WorkflowTransitionError,
    coder_actor,
    mark_coder_finalized,
    mark_coder_not_codeable,
    mark_coder_step1_saved,
    mark_recode_finalized,
)
from app.services.forms.type_resolution import (
    va_get_form_type_code_for_form,
)

from ..helpers import (
    _demo_expiry_for_actiontype,
    _is_social_autopsy_enabled_for_submission,
    adult,
    children,
    neonate,
)

log = logging.getLogger(__name__)


def handle_reviewer_review(va_sid, va_partial, va_action, va_actiontype):
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
                VaReviewerReview.payload_version_id == active_payload_version.payload_version_id,
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
            existing_review.va_rreview_remark = form.va_rreview_remark.data.strip() or None
            existing_review.payload_version_id = active_payload_version.payload_version_id
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
        f"va_form_partials/{va_partial}.html",
        form=form,
        va_action=va_action,
        va_actiontype=va_actiontype,
        va_sid=va_sid,
    )


def handle_workflow_history(va_sid):
    events = db.session.scalars(
        sa.select(VaSubmissionWorkflowEvent)
        .where(VaSubmissionWorkflowEvent.va_sid == va_sid)
        .order_by(VaSubmissionWorkflowEvent.event_created_at)
    ).all()
    return render_template("va_form_partials/workflow_history.html", va_sid=va_sid, events=events)


def handle_initial_assessment(va_sid, va_partial, va_action, va_actiontype, va_payload_data):
    form = VaInitialAssessmentForm()
    save_clicked = form.va_save_assessment.data
    not_codeable_clicked = form.va_not_codeable.data
    agelabels = {
        "isNeonatal": (va_payload_data or {}).get("isNeonatal"),
        "isChild": (va_payload_data or {}).get("isChild"),
        "isAdult": (va_payload_data or {}).get("isAdult"),
    }
    active_age_label = next((k for k, v in agelabels.items() if str(v).strip() in ("1", "1.0")), None)
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
        smartva = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                (VaSmartvaResults.va_sid == va_sid)
                & (VaSmartvaResults.va_smartva_status == VaStatuses.active)
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
        gen_uuid = uuid.uuid4()
        new_review = VaInitialAssessments(
            va_iniassess_id=gen_uuid,
            va_sid=va_sid,
            va_iniassess_by=current_user.user_id,
            va_immediate_cod=form.va_immediate_cod.data,
            va_antecedent_cod=form.va_antecedent_cod.data,
            va_other_conditions=" | ".join(form.va_other_conditions.data)
            if form.va_other_conditions.data
            else None,
        )
        db.session.add(new_review)
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=current_user.user_id,
                va_audit_operation="c",
                va_audit_action="initial cod submitted",
                va_audit_entityid=gen_uuid,
            )
        )
        current_state = get_submission_workflow_state(va_sid)
        session_timed_out = current_state == WORKFLOW_READY_FOR_CODING
        step1_resaved = current_state == WORKFLOW_CODER_STEP1_SAVED
        try:
            mark_coder_step1_saved(
                va_sid,
                reason="initial_cod_updated" if step1_resaved else "initial_cod_submitted",
                actor=coder_actor(current_user.user_id),
            )
        except WorkflowTransitionError:
            log.warning(
                "coder_step1_saved blocked | sid=%s | current_state=%r | coder_user_id=%s",
                va_sid,
                current_state,
                current_user.user_id,
            )
            raise
        db.session.commit()
        va_initial_assess = db.session.scalar(
            sa.select(VaInitialAssessments).where(
                (VaInitialAssessments.va_iniassess_status == VaStatuses.active)
                & (VaInitialAssessments.va_sid == va_sid)
            )
        )
        return render_template(
            "va_form_partials/vafinalasses.html",
            form=form1,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            smartva=smartva,
            va_immediate_cod=va_initial_assess.va_immediate_cod or None,
            va_antecedent_cod=va_initial_assess.va_antecedent_cod or None,
            va_other_conditions=va_initial_assess.va_other_conditions or None,
            session_timed_out=session_timed_out,
            step1_resaved=step1_resaved,
        )
    if not_codeable_clicked:
        form2 = VaCoderReviewForm()
        return render_template(
            "va_form_partials/vacoderreview.html",
            form=form2,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
        )
    existing_assess = db.session.scalar(
        sa.select(VaInitialAssessments)
        .where(
            VaInitialAssessments.va_sid == va_sid,
            VaInitialAssessments.va_iniassess_by == current_user.user_id,
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        )
        .order_by(VaInitialAssessments.va_iniassess_createdat.desc())
    )
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


def handle_final_assessment(va_sid, va_partial, va_action, va_actiontype):
    form1 = VaFinalAssessmentForm()
    smartva = db.session.scalar(
        sa.select(VaSmartvaResults).where(
            (VaSmartvaResults.va_sid == va_sid)
            & (VaSmartvaResults.va_smartva_status == VaStatuses.active)
        )
    )
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
    if prior_authoritative_final and prior_authoritative_final.source_initial_assessment_id:
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
                prior_authoritative_final.va_conclusive_cod if prior_authoritative_final else None
            ),
            previous_final_conclusive_cod=(
                prior_authoritative_final.va_conclusive_cod if prior_authoritative_final else None
            ),
            previous_final_immediate_cod=(
                prior_final_initial.va_immediate_cod if prior_final_initial else None
            ),
            previous_final_antecedent_cod=(
                prior_final_initial.va_antecedent_cod if prior_final_initial else None
            ),
            form_error_messages=error_messages or [],
        )

    if form1.validate_on_submit():
        blocking_messages: list[str] = []
        from app.services.projects.submission_lookup import get_project_for_submission
        from app.services.forms.category_rendering import (
            get_category_rendering_service,
            get_visible_category_codes,
        )

        _project = get_project_for_submission(va_sid)
        if _project and _project.narrative_qa_enabled:
            _nqa_done = get_current_payload_narrative_assessment(va_sid, current_user.user_id)
            if not _nqa_done:
                blocking_messages.append(
                    "Narrative Quality Assessment must be completed before submitting the final COD."
                )
        _submission = db.session.get(VaSubmissions, va_sid)
        _sub_active_version = get_active_payload_version(va_sid) if _submission else None
        _sub_payload_data = _sub_active_version.payload_data if _sub_active_version else None
        _form_type_code = va_get_form_type_code_for_form(_submission.va_form_id if _submission else None)
        _visible_category_codes = get_visible_category_codes(
            _sub_payload_data,
            _submission.va_form_id if _submission else None,
        )
        _category_service = form_routes.get_category_rendering_service()
        if (
            _is_social_autopsy_enabled_for_submission(va_sid)
            and _category_service.is_category_enabled(
                _form_type_code,
                "vacode",
                _visible_category_codes,
                "social_autopsy",
            )
        ):
            _social_done = get_current_payload_social_autopsy_analysis(va_sid, current_user.user_id)
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
        active_payload_version = get_active_payload_version(va_sid)
        if active_payload_version is None:
            raise ValueError(f"Submission {va_sid} has no active payload version.")
        active_recode_episode = get_active_recode_episode(va_sid)
        prior_authoritative_final = get_authoritative_final_assessment(va_sid)
        existing_active_finals = db.session.scalars(
            sa.select(VaFinalAssessments).where(
                VaFinalAssessments.va_sid == va_sid,
                VaFinalAssessments.payload_version_id == active_payload_version.payload_version_id,
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
            va_finassess_remark=form1.va_finassess_remark.data.strip() or None,
            demo_expires_at=_demo_expiry_for_actiontype(va_sid, va_actiontype),
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
                        and existing_final.va_finassess_id == prior_authoritative_final.va_finassess_id
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
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=current_user.user_id,
                va_audit_operation="c",
                va_audit_action="final cod submitted",
                va_audit_entityid=gen_uuid,
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
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=current_user.user_id,
                va_audit_operation="d",
                va_audit_action="allocated form released from coder",
                va_audit_entityid=va_has_allocation.va_allocation_id,
            )
        )
        db.session.flush()
        upsert_final_cod_authority(
            va_sid,
            new_review1,
            reason="replacement_final_cod_submitted" if active_recode_episode else "final_cod_submitted",
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
        form_routes.bust_coder_dashboard_cache(current_user.user_id)
        if request.headers.get("HX-Request"):
            response = jsonify(success=True)
            response.headers["HX-Redirect"] = url_for("coding.dashboard")
            flash("VA Coding submitted successfully!", "success")
            return response
    return _render_final_assessment_form()


def handle_user_note(va_sid, va_partial, va_action, va_actiontype):
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
            db.session.add(
                VaUsernotes(
                    note_by=current_user.user_id,
                    note_vasubmission=va_sid,
                    note_content=form.va_note_content.data,
                )
            )
        db.session.commit()
        obb_response = render_template(
            "va_intermediate_partials/va_note_notification.html",
            message="Note Saved!",
        )
        main_response = render_template(
            f"va_form_partials/{va_partial}.html",
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            form=form,
        )
        return obb_response + main_response
    form.va_note_content.data = va_usernote.note_content if va_usernote else ""
    return render_template(
        f"va_form_partials/{va_partial}.html",
        va_action=va_action,
        va_actiontype=va_actiontype,
        va_sid=va_sid,
        form=form,
    )


def handle_coder_review(va_sid, va_partial, va_action, va_actiontype):
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
            va_creview_id=gen_uuid,
            va_sid=va_sid,
            va_creview_by=current_user.user_id,
            va_creview_reason=form.va_creview_reason.data,
            va_creview_other=other_reason,
        )
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=current_user.user_id,
                va_audit_operation="c",
                va_audit_action="error reported by coder",
                va_audit_entityid=gen_uuid,
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
                va_sid=va_sid,
                va_audit_byrole="vacoder",
                va_audit_by=current_user.user_id,
                va_audit_operation="d",
                va_audit_action="allocated form released from coder",
                va_audit_entityid=va_has_allocation.va_allocation_id,
            )
        )
        db.session.add(new_coder_review)
        mark_coder_not_codeable(
            va_sid,
            reason="coder_marked_not_codeable",
            actor=coder_actor(current_user.user_id),
        )
        odk_sync_result = form_routes.sync_not_codeable_review_state(
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
        form_routes.bust_coder_dashboard_cache(current_user.user_id)
        if request.headers.get("HX-Request"):
            response = jsonify(success=True)
            response.headers["HX-Redirect"] = url_for("coding.dashboard")
            return response
    return _render_coder_review_form()
