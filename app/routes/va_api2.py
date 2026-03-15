# an attempt to refactor and clean htmx api..
# add time taken to code a form as instructed by dr. rakesh
import os
import uuid
import math
from app import db
import sqlalchemy as sa
from datetime import datetime
from flask_login import current_user, login_required

from app.decorators import va_validate_permissions
from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    send_from_directory,
    current_app,
)
from app.forms import (
    VaCoderReviewForm,
    VaFinalAssessmentForm,
    VaInitialAssessmentForm,
    VaReviewerReviewForm,
    VaUsernoteForm,
)
from app.models import (
    VaAllocation,
    VaCoderReview,
    VaFinalAssessments,
    VaIcdCodes,
    VaInitialAssessments,
    VaReviewerReview,
    VaUsernotes,
)
from app.utils import (
    va_permission_abortwithflash,
    VA_RENDER_FOR_ALL,
    va_assign_other_condition_choices,
    va_deactivate_allocation,
    va_get_active_initial_assessment,
    va_get_active_smartva_result,
    va_get_age_labels,
    va_get_category_context,
    va_get_user_note_for_current_user,
    va_handle_htmx_redirect,
    va_log_submission_action,
    va_render_category_partial,
    va_request_is_htmx,
)

va_api = Blueprint("va_api", __name__)


@va_api.route("/<va_action>/<va_actiontype>/<va_sid>/<va_partial>", methods=["GET", "POST"])
@login_required
@va_validate_permissions()
def va_renderpartial(va_action, va_actiontype, va_sid, va_partial):
    if va_partial in VA_RENDER_FOR_ALL:
        context = va_get_category_context(va_sid, va_action, va_partial)
        if context:
            return va_render_category_partial(
                context, va_action, va_actiontype, va_sid, va_partial
            )

    if va_partial == "vareviewform":
        form = VaReviewerReviewForm()
        if form.validate_on_submit():
            new_review = VaReviewerReview(
                va_sid=va_sid,
                va_rreview_by=current_user.user_id,
                va_rreview_narrpos=form.va_rreview_narrpos.data,
                va_rreview_narrneg=form.va_rreview_narrneg.data,
                va_rreview_narrchrono=form.va_rreview_narrchrono.data,
                va_rreview_narrdoc=form.va_rreview_narrdoc.data,
                va_rreview_narrcomorb=form.va_rreview_narrcomorb.data,
                va_rreview=form.va_rreview.data,
                va_rreview_fail=form.va_rreview_fail.data.strip() or None,
                va_rreview_remark=form.va_rreview_remark.data.strip() or None,
            )
            allocation = va_deactivate_allocation(
                current_user.user_id, VaAllocation.reviewing
            )
            db.session.add(new_review)
            db.session.commit()

            if va_request_is_htmx():
                return va_handle_htmx_redirect(
                    "va_main.va_dashboard",
                    "reviewer",
                    "Review submitted successfully!",
                )
        return render_template(
            f"va_form_partials/{va_partial}.html",
            form=form,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
        )

    if va_partial == "vainitialasses":
        form = VaInitialAssessmentForm()
        agelabels = va_get_age_labels(va_sid)
        va_assign_other_condition_choices(form, agelabels)

        if form.va_save_assessment.data and form.validate_on_submit():
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
            va_log_submission_action(
                va_sid=va_sid,
                role="vacoder",
                action="initial cod submitted",
                entity_id=gen_uuid,
            )
            db.session.commit()
            va_initial_assess = va_get_active_initial_assessment(va_sid)
            return render_template(
                "va_form_partials/vafinalasses.html",
                form=VaFinalAssessmentForm(),
                va_action=va_action,
                va_actiontype=va_actiontype,
                va_sid=va_sid,
                smartva=va_get_active_smartva_result(va_sid),
                va_immediate_cod=va_initial_assess.va_immediate_cod
                if va_initial_assess
                else None,
                va_antecedent_cod=va_initial_assess.va_antecedent_cod
                if va_initial_assess
                else None,
                va_other_conditions=va_initial_assess.va_other_conditions
                if va_initial_assess
                else None,
            )

        if form.va_not_codeable.data:
            return render_template(
                "va_form_partials/vacoderreview.html",
                form=VaCoderReviewForm(),
                va_action=va_action,
                va_actiontype=va_actiontype,
                va_sid=va_sid,
            )

        return render_template(
            f"va_form_partials/{va_partial}.html",
            form=form,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
        )

    if va_partial == "vafinalasses":
        form = VaFinalAssessmentForm()
        smartva = va_get_active_smartva_result(va_sid)
        if form.validate_on_submit():
            gen_uuid = uuid.uuid4()
            allocation = va_deactivate_allocation(
                current_user.user_id, VaAllocation.coding
            )
            if allocation:
                va_log_submission_action(
                    va_sid=va_sid,
                    role="vacoder",
                    action="allocated form released from coder",
                    entity_id=allocation.va_allocation_id,
                    operation="d",
                )
                va_time_to_code = datetime.now() - allocation.va_allocation_createdat
                va_time_to_code = math.ceil(va_time_to_code.total_seconds() / 60)
            else:
                va_time_to_code = 0
            new_review = VaFinalAssessments(
                va_finassess_id=gen_uuid,
                va_sid=va_sid,
                va_finassess_by=current_user.user_id,
                va_conclusive_cod=form.va_conclusive_cod.data,
                va_finassess_remark=form.va_finassess_remark.data.strip() or None,
                va_time_to_code=va_time_to_code,
            )
            db.session.add(new_review)
            va_log_submission_action(
                va_sid=va_sid,
                role="vacoder",
                action="final cod submitted",
                entity_id=gen_uuid,
            )
            
            db.session.commit()

            if va_request_is_htmx():
                return va_handle_htmx_redirect(
                    "va_main.va_dashboard",
                    "coder",
                    "VA Coding submitted successfully!",
                )

        va_initial_assess = va_get_active_initial_assessment(va_sid)
        return render_template(
            f"va_form_partials/{va_partial}.html",
            form=form,
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            smartva=smartva,
            va_immediate_cod=va_initial_assess.va_immediate_cod
            if va_initial_assess
            else None,
            va_antecedent_cod=va_initial_assess.va_antecedent_cod
            if va_initial_assess
            else None,
            va_other_conditions=va_initial_assess.va_other_conditions
            if va_initial_assess
            else None,
        )

    if va_partial == "vausernote":
        form = VaUsernoteForm()
        va_usernote = va_get_user_note_for_current_user(va_sid)

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

    if va_partial == "vacoderreview":
        form = VaCoderReviewForm()
        if form.validate_on_submit():
            gen_uuid = uuid.uuid4()
            new_coder_review = VaCoderReview(
                va_creview_id=gen_uuid,
                va_sid=va_sid,
                va_creview_by=current_user.user_id,
                va_creview_reason=form.va_creview_reason.data,
                va_creview_other=form.va_creview_other.data.strip() or None,
            )
            db.session.add(new_coder_review)
            va_log_submission_action(
                va_sid=va_sid,
                role="vacoder",
                action="error reported by coder",
                entity_id=gen_uuid,
            )
            allocation = va_deactivate_allocation(
                current_user.user_id, VaAllocation.coding
            )
            if allocation:
                va_log_submission_action(
                    va_sid=va_sid,
                    role="vacoder",
                    action="allocated form released from coder",
                    entity_id=allocation.va_allocation_id,
                    operation="d",
                )
            db.session.commit()
            if va_request_is_htmx():
                return va_handle_htmx_redirect(
                    "va_main.va_dashboard",
                    "coder",
                    "Error reported successfully!",
                )
        return render_template(
            f"va_form_partials/{va_partial}.html",
            va_action=va_action,
            va_actiontype=va_actiontype,
            va_sid=va_sid,
            form=form,
        )

    if va_partial in VA_RENDER_FOR_ALL:
        context = va_get_category_context(va_sid, va_action, va_partial)
        if context:
            return va_render_category_partial(
                context, va_action, va_actiontype, va_sid, va_partial
            )

    return va_permission_abortwithflash("Invalid partial requested", 404)


@va_api.route("/vaservemedia/<va_form_id>/<va_filename>")
@login_required
def va_servemedia(va_form_id, va_filename):
    if not current_user.has_va_form_access(va_form_id):
        va_permission_abortwithflash(
            f"You don't have permissions to access the media files for '{va_form_id}'",
            403,
        )

    # Validate form_id format to prevent path traversal
    if not va_form_id or not re.match(r'^[A-Za-z0-9_-]+$', va_form_id):
        abort(400, description="Invalid form ID format")

    # Sanitize filename to safe_fn = secure_filename(va_filename)
    if not safe_fn or '..' in va_filename or va_filename.startswith('\\'):
        abort(400, description="Invalid filename")

    media_base = os.path.join(current_app.config["APP_DATA"], va_form_id, "media")
    return send_from_directory(media_base, safe_fn)


@va_api.route("/icd-search")
@login_required
def icd_search():
    query = request.args.get("q", "")
    results = db.session.execute(
        sa.select(VaIcdCodes.icd_code, VaIcdCodes.icd_to_display)
        .where(VaIcdCodes.icd_to_display.ilike(f"%{query}%"))
        .limit(20)
    ).all()
    return jsonify([{"icd_code": r[0], "icd_to_display": r[1]} for r in results])
