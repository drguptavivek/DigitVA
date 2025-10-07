import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaStatuses, VaCoderReview, VaFinalAssessments
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_ensureviewable(sid):
    final_ids = db.session.scalars(
        sa.select(VaFinalAssessments.va_sid)
        .where(
            (VaFinalAssessments.va_finassess_by == current_user.user_id)
            & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
        )
    ).all()
    review_ids = db.session.scalars(
        sa.select(VaCoderReview.va_sid)
        .where(
            (VaCoderReview.va_creview_by == current_user.user_id)
            & (VaCoderReview.va_creview_status == VaStatuses.active)
        )
    ).all()
    if sid not in final_ids + review_ids:
        va_permission_abortwithflash(
            "You no longer have access to view this VA form.", 403
        )
