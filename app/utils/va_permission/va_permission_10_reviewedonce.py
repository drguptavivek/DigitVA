import sqlalchemy as sa
from app import db
from app.models import VaStatuses, VaReviewerReview
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_reviewedonce(sid):
    reviewed = db.session.scalar(
        sa.select(VaReviewerReview.va_sid).where(
            (VaReviewerReview.va_sid == sid)
            & (VaReviewerReview.va_rreview_status == VaStatuses.active)
        )
    )
    if not reviewed:
        va_permission_abortwithflash(
            "This VA form must be reviewed atleast once before requesting a re-review.",
            403,
        )
