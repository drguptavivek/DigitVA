import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaReviewerFinalAssessments, VaReviewerReview, VaStatuses
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_ensurereviewed(sid):
    # A form is considered "reviewed" by the current user when they have
    # submitted either:
    # - a reviewer final COD (VaReviewerFinalAssessments — new secondary-coding
    #   model), or
    # - an NQA record (VaReviewerReview — NQA supporting artifact; covers
    #   projects where NQA is the only reviewer action).
    has_final_cod = db.session.scalar(
        sa.select(VaReviewerFinalAssessments.va_sid).where(
            (VaReviewerFinalAssessments.va_sid == sid)
            & (VaReviewerFinalAssessments.va_rfinassess_by == current_user.user_id)
            & (VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active)
        )
    )
    has_nqa = db.session.scalar(
        sa.select(VaReviewerReview.va_sid).where(
            (VaReviewerReview.va_sid == sid)
            & (VaReviewerReview.va_rreview_by == current_user.user_id)
            & (VaReviewerReview.va_rreview_status == VaStatuses.active)
        )
    )
    if not has_final_cod and not has_nqa:
        va_permission_abortwithflash(
            "You do not have access to view this reviewed VA form.", 403
        )
