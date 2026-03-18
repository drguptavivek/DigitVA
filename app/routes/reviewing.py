import uuid
import sqlalchemy as sa
from app import db
from app.models import VaSubmissions, VaAllocations, VaAllocation, VaStatuses, VaReviewerReview, VaSubmissionsAuditlog, VaSubmissionWorkflow
from flask_login import current_user, login_required
from flask import Blueprint, render_template, url_for
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.utils import va_permission_ensurenotreviewed, va_permission_ensureanyallocation, va_permission_ensurereviewed
from app.services.coding_service import render_va_coding_page

reviewing = Blueprint("reviewing", __name__)


@reviewing.get("/")
@login_required
def dashboard():
    if not current_user.is_reviewer():
        va_permission_abortwithflash("Reviewer access is required.", 403)

    va_form_access = current_user.get_reviewer_va_forms()
    if va_form_access:
        va_total_forms = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSubmissions)
            .where(
                sa.sql.and_(
                    VaSubmissions.va_form_id.in_(va_form_access),
                    VaSubmissions.va_narration_language.in_(
                        current_user.vacode_language
                    ),
                )
            )
        )
        va_forms_completed = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaReviewerReview)
            .where(
                sa.sql.and_(
                    VaReviewerReview.va_rreview_by == current_user.user_id,
                    VaReviewerReview.va_rreview_status == VaStatuses.active,
                )
            )
        )
        va_forms_raw = (
            db.session.execute(
                sa.select(
                    sa.func.date(VaSubmissions.va_submission_date).label(
                        "va_submission_date"
                    ),
                    VaSubmissions.va_form_id,
                    VaSubmissions.va_sid,
                    VaSubmissions.va_uniqueid_masked,
                    VaSubmissions.va_data_collector,
                    VaSubmissions.va_deceased_age,
                    VaSubmissions.va_deceased_gender,
                    sa.case(
                        (
                            VaReviewerReview.va_rreview_status == VaStatuses.active,
                            sa.literal("Reviewed"),
                        ),
                        else_=sa.literal("Not Reviewed"),
                    ).label("va_review_status"),
                    sa.func.date(VaReviewerReview.va_rreview_createdat).label(
                        "va_rreview_createdat"
                    ),
                    VaReviewerReview.va_rreview_by,
                )
                .outerjoin(
                    VaReviewerReview,
                    sa.sql.and_(
                        VaReviewerReview.va_sid == VaSubmissions.va_sid,
                        VaReviewerReview.va_rreview_status == VaStatuses.active,
                    ),
                )
                .where(
                    sa.sql.and_(
                        VaSubmissions.va_form_id.in_(va_form_access),
                        VaSubmissions.va_narration_language.in_(
                            current_user.vacode_language
                        ),
                    )
                )
            )
            .mappings()
            .all()
        )
        va_date_fields = ["va_submission_date", "va_rreview_createdat"]
        va_forms = [
            va_render_serialisedates(row, va_date_fields) for row in va_forms_raw
        ]
    else:
        va_total_forms = 0
        va_forms_completed = 0
        va_forms = []
    va_has_allocation = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == current_user.user_id)
            & (VaAllocations.va_allocation_for == VaAllocation.reviewing)
            & (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    return render_template(
        "va_frontpages/va_reviewer.html",
        va_total_forms=va_total_forms,
        va_forms_completed=va_forms_completed,
        va_forms=va_forms,
        va_has_allocation=va_has_allocation,
    )


@reviewing.get("/start/<va_sid>")
@login_required
def start(va_sid):
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not current_user.has_va_form_access(form.va_form_id, "reviewer"):
        va_permission_abortwithflash("Reviewer access is required.", 403)
    if form.va_narration_language not in current_user.vacode_language:
        va_permission_abortwithflash(f"Your profile does not support reviewing forms in {form.va_narration_language}.", 403)
    va_permission_ensurenotreviewed(va_sid)
    # Create allocation
    gen_uuid = uuid.uuid4()
    db.session.add(VaAllocations(
        va_allocation_id=gen_uuid,
        va_sid=va_sid,
        va_allocated_to=current_user.user_id,
        va_allocation_for=VaAllocation.reviewing,
    ))
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="vacoder",
        va_audit_by=current_user.user_id,
        va_audit_operation="c",
        va_audit_action="form allocated to reviewer",
        va_audit_entityid=gen_uuid,
    ))
    db.session.commit()
    return render_va_coding_page(form, "vareview", "vastartreviewing", "reviewer")


@reviewing.get("/resume")
@login_required
def resume():
    if not current_user.is_reviewer():
        va_permission_abortwithflash("Reviewer access is required.", 403)
    va_permission_ensureanyallocation("reviewing")
    va_sid = db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            (VaAllocations.va_allocated_to == current_user.user_id) &
            (VaAllocations.va_allocation_for == VaAllocation.reviewing) &
            (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    )
    form = db.session.get(VaSubmissions, va_sid)
    return render_va_coding_page(form, "vareview", "varesumereviewing", "reviewer")


@reviewing.get("/view/<va_sid>")
@login_required
def view_submission(va_sid):
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    if not current_user.has_va_form_access(form.va_form_id, "reviewer"):
        va_permission_abortwithflash("Reviewer access is required.", 403)
    va_permission_ensurereviewed(va_sid)
    return render_va_coding_page(form, "vareview", "vaview", "reviewer")
