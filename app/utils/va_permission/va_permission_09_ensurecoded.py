import sqlalchemy as sa
from app import db
from app.models import VaStatuses, VaCoderReview, VaFinalAssessments
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_ensurecoded(sid):
    coded = db.session.scalar(
        sa.select(VaCoderReview.va_sid).where(
            (VaCoderReview.va_sid == sid)
            & (VaCoderReview.va_creview_status == VaStatuses.active)
        )
    ) or db.session.scalar(
        sa.select(VaFinalAssessments.va_sid).where(
            (VaFinalAssessments.va_sid == sid)
            & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
        )
    )
    if not coded:
        va_permission_abortwithflash(
            "This VA form must be coded before requesting a re-code.", 403
        )
