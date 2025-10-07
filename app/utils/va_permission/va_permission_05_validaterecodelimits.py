import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaStatuses, VaCoderReview, VaFinalAssessments
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_validaterecodelimits(sid):
    review = (
        db.session.execute(
            sa.select(VaCoderReview.va_sid
            ).where(
                (VaCoderReview.va_creview_by == current_user.user_id)
                & (VaCoderReview.va_sid == sid)
                & (VaCoderReview.va_creview_status == VaStatuses.active)
            )
        )
        .mappings()
        .first()
    )
    final = (
        db.session.execute(
            sa.select(
                VaFinalAssessments.va_sid
            ).where(
                (VaFinalAssessments.va_finassess_by == current_user.user_id)
                & (VaFinalAssessments.va_sid == sid)
                & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
            )
        )
        .mappings()
        .first()
    )
    if not ((review and review["va_sid"]) or (final and final["va_sid"])):
        va_permission_abortwithflash(
            "You can only re-code VA forms you initially coded.", 403
        )
    review24hours = (
        db.session.execute(
            sa.select(VaCoderReview.va_sid
            ).where(
                (VaCoderReview.va_creview_by == current_user.user_id)
                & (VaCoderReview.va_sid == sid)
                & (
                    VaCoderReview.va_creview_createdat
                    + sa.text("interval '24 hours'")
                    > sa.func.now()
                )
            )
        )
        .mappings()
        .all()
    )
    final24hours = (
        db.session.execute(
            sa.select(
                VaFinalAssessments.va_sid
            ).where(
                (VaFinalAssessments.va_finassess_by == current_user.user_id)
                & (VaFinalAssessments.va_sid == sid)
                & (
                    VaFinalAssessments.va_finassess_createdat
                    + sa.text("interval '24 hours'")
                    > sa.func.now()
                )
            )
        )
        .mappings()
        .all()
    )
    if len(review24hours + final24hours) > 1:
        va_permission_abortwithflash(
            "You have already re-coded this VA form once in the last 24 hours.", 403
        )
    recent_final = db.session.scalars(
        sa.select(VaFinalAssessments.va_sid).where(
            (VaFinalAssessments.va_finassess_by == current_user.user_id)
            & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
            & (
                VaFinalAssessments.va_finassess_createdat
                + sa.text("interval '24 hours'")
                > sa.func.now()
            )
        )
    ).all()
    recent_review = db.session.scalars(
        sa.select(VaCoderReview.va_sid).where(
            (VaCoderReview.va_creview_by == current_user.user_id)
            & (VaCoderReview.va_creview_status == VaStatuses.active)
            & (
                VaCoderReview.va_creview_createdat + sa.text("interval '24 hours'")
                > sa.func.now()
            )
        )
    ).all()
    if sid not in recent_final + recent_review:
        va_permission_abortwithflash(
            "Re-coding is only allowed within 24 hours of VA form finalisation.", 403
        )
