import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaStatuses, VaReviewerReview
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_ensurereviewed(sid):
    viewable = db.session.scalar(
        sa.select(VaReviewerReview.va_sid).where(
            (VaReviewerReview.va_sid == sid)
            & (VaReviewerReview.va_rreview_by == current_user.user_id)
            & (VaReviewerReview.va_rreview_status == VaStatuses.active)
        )
    )
    if not viewable:
        va_permission_abortwithflash(
            "You do not have access to view this reviewed VA form.", 403
        )
