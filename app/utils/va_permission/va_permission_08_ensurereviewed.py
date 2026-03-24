import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaReviewerFinalAssessments, VaStatuses
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_ensurereviewed(sid):
    # Grants post-session view access to the reviewer who submitted the final
    # COD for this submission. Workflow state alone cannot answer "did THIS
    # user do the review", so we check VaReviewerFinalAssessments directly.
    # NQA and Social Autopsy are supporting artifacts — submitting them does
    # not grant view access on their own.
    has_final_cod = db.session.scalar(
        sa.select(VaReviewerFinalAssessments.va_sid).where(
            (VaReviewerFinalAssessments.va_sid == sid)
            & (VaReviewerFinalAssessments.va_rfinassess_by == current_user.user_id)
            & (VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active)
        )
    )
    if not has_final_cod:
        va_permission_abortwithflash(
            "You do not have access to view this reviewed VA form.", 403
        )
