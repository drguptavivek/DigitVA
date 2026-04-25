import logging
from datetime import datetime, timedelta, timezone

from flask import render_template, request
from flask_login import current_user, login_required

from app import db
from app.authz.access import dynamic_action_authorized
from app.authz.resources import submission_from_kwarg
from app.decorators.va_validate_permissions import validate_va_request
from app.models import (
    VaSubmissions,
)
from app.services.category_rendering_service import get_category_rendering_service
from app.services.odk.review import sync_not_codeable_review_state
from app.services.coder_dashboard_service import bust_coder_dashboard_cache
from app.utils import va_permission_abortwithflash
from .handlers import (
    handle_category_partial,
    handle_coder_review,
    handle_final_assessment,
    handle_initial_assessment,
    handle_reviewer_review,
    handle_user_note,
    handle_workflow_history,
)

import app.routes.forms as form_routes
from . import va_form
from .helpers import (
    _invalidate_section_data_cache,
)

log = logging.getLogger(__name__)


def _resolve_renderpartial_action(va_sid, va_partial):
    resource = submission_from_kwarg("va_sid")(va_sid=va_sid)
    va_action = request.values.get("action", "vacode")
    if va_partial == "workflow_history":
        return "workflow_history_view", resource
    if va_partial == "vausernote" and request.method == "POST":
        return "submission_user_note_save", resource
    if va_partial == "vadmtriage":
        return (
            "dm_triage_save" if request.method == "POST" else "dm_triage_view",
            resource,
        )
    if va_partial == "vareviewform" and request.method == "POST":
        return "reviewing_nqa_save", resource
    if va_partial == "vafinalasses" and request.method == "POST":
        return "coding_final_assessment_submit", resource
    if (
        va_partial == "vainitialasses"
        and request.method == "POST"
        and request.form.get("va_save_assessment")
    ):
        return "coding_initial_assessment_save", resource
    if va_partial == "vacoderreview" and request.method == "POST":
        return "coding_not_codeable_submit", resource
    action_map = {
        "vacode": "va_form_section_view_coding",
        "vareview": "va_form_section_view_reviewing",
        "vasitepi": "va_form_section_view_sitepi",
        "vadata": "va_form_section_view_dm",
    }
    return action_map.get(va_action), resource

@va_form.route("/<va_sid>/<va_partial>", methods=["GET", "POST"])
@login_required
@dynamic_action_authorized(_resolve_renderpartial_action)
def renderpartial(va_sid, va_partial):
    va_action = request.values.get("action", "vacode")
    va_actiontype = request.values.get("actiontype", "")
    validate_va_request(
        va_action=va_action,
        va_actiontype=va_actiontype,
        va_sid=va_sid,
        va_partial=va_partial,
    )
    va_submission = db.session.get(VaSubmissions, va_sid)
    from app.services.submission_payload_version_service import get_active_payload_version

    _active_version = get_active_payload_version(va_sid) if va_submission else None
    va_payload_data = _active_version.payload_data if _active_version else None
    category_response = handle_category_partial(
        va_sid,
        va_partial,
        va_action,
        va_actiontype,
        va_submission,
        va_payload_data,
    )
    if category_response is not None:
        return category_response
    if va_partial == "vareviewform":
        return handle_reviewer_review(va_sid, va_partial, va_action, va_actiontype)
    if va_partial == "workflow_history":
        return handle_workflow_history(va_sid)
    if va_partial == "vainitialasses":
        return handle_initial_assessment(
            va_sid,
            va_partial,
            va_action,
            va_actiontype,
            va_payload_data,
        )
    if va_partial == "vafinalasses":
        return handle_final_assessment(va_sid, va_partial, va_action, va_actiontype)
    if va_partial == "vausernote":
        return handle_user_note(va_sid, va_partial, va_action, va_actiontype)
    if va_partial == "vacoderreview":
        return handle_coder_review(va_sid, va_partial, va_action, va_actiontype)
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
