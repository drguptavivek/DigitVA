import sqlalchemy as sa
from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaReviewerFinalAssessments,
    VaReviewerReview,
    VaStatuses,
    VaSubmissions,
)
from flask_login import current_user, login_required
from flask import Blueprint, render_template
from app.utils import va_permission_abortwithflash, va_render_serialisedates
from app.utils import va_permission_ensureanyallocation, va_permission_ensurereviewed
from app.services.coding_service import render_va_coding_page
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    get_active_reviewing_allocation,
    start_reviewer_coding,
)

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
        # "Completed" means the reviewer submitted either a final COD
        # (VaReviewerFinalAssessments — new model) or an NQA record
        # (VaReviewerReview — legacy/NQA-only projects).
        va_forms_completed = db.session.scalar(
            sa.select(sa.func.count(sa.distinct(VaSubmissions.va_sid)))
            .select_from(VaSubmissions)
            .outerjoin(
                VaReviewerFinalAssessments,
                sa.and_(
                    VaReviewerFinalAssessments.va_sid == VaSubmissions.va_sid,
                    VaReviewerFinalAssessments.va_rfinassess_by == current_user.user_id,
                    VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
                ),
            )
            .outerjoin(
                VaReviewerReview,
                sa.and_(
                    VaReviewerReview.va_sid == VaSubmissions.va_sid,
                    VaReviewerReview.va_rreview_by == current_user.user_id,
                    VaReviewerReview.va_rreview_status == VaStatuses.active,
                ),
            )
            .where(
                sa.or_(
                    VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
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
                    # "Reviewed" when either reviewer final COD (new model) or
                    # NQA (VaReviewerReview, legacy/NQA-only projects) exists.
                    sa.case(
                        (
                            sa.or_(
                                VaReviewerFinalAssessments.va_rfinassess_status
                                == VaStatuses.active,
                                VaReviewerReview.va_rreview_status == VaStatuses.active,
                            ),
                            sa.literal("Reviewed"),
                        ),
                        else_=sa.literal("Not Reviewed"),
                    ).label("va_review_status"),
                    sa.func.date(
                        sa.func.coalesce(
                            VaReviewerFinalAssessments.va_rfinassess_createdat,
                            VaReviewerReview.va_rreview_createdat,
                        )
                    ).label("va_reviewed_at"),
                )
                .outerjoin(
                    VaReviewerFinalAssessments,
                    sa.and_(
                        VaReviewerFinalAssessments.va_sid == VaSubmissions.va_sid,
                        VaReviewerFinalAssessments.va_rfinassess_status
                        == VaStatuses.active,
                    ),
                )
                .outerjoin(
                    VaReviewerReview,
                    sa.and_(
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
        va_date_fields = ["va_submission_date", "va_reviewed_at"]
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
    try:
        result = start_reviewer_coding(current_user, va_sid)
    except ReviewerCodingError as exc:
        va_permission_abortwithflash(exc.message, exc.status_code)

    form = db.session.get(VaSubmissions, result.va_sid)
    return render_va_coding_page(form, "vareview", result.actiontype, "reviewer")


@reviewing.get("/resume")
@login_required
def resume():
    if not current_user.is_reviewer():
        va_permission_abortwithflash("Reviewer access is required.", 403)
    va_permission_ensureanyallocation("reviewing")
    va_sid = get_active_reviewing_allocation(current_user.user_id)
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
