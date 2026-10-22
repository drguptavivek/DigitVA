import sqlalchemy as sa
from app import db
from flask_login import current_user
from app.models import VaStatuses, VaCoderReview, VaFinalAssessments
from app.services.recode_window import recode_window_for_submission, recode_window_label
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash


def va_permission_validaterecodelimits(sid):
    message = recode_limit_error(current_user, sid)
    if message:
        va_permission_abortwithflash(message, 403)


def recode_limit_error(user, sid) -> str | None:
    """Why *user* may not recode *sid*, or None when they may.

    The ownership and recode-window rule shared by the ``varecode`` validator
    and ``start_recode_allocation``: only the coder who finalized (or
    reviewed) the submission, once, within the project's recode window
    (``app/services/recode_window.py``) of finalisation.
    """
    review = (
        db.session.execute(
            sa.select(VaCoderReview.va_sid
            ).where(
                (VaCoderReview.va_creview_by == user.user_id)
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
                (VaFinalAssessments.va_finassess_by == user.user_id)
                & (VaFinalAssessments.va_sid == sid)
                & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
            )
        )
        .mappings()
        .first()
    )
    if not ((review and review["va_sid"]) or (final and final["va_sid"])):
        return "You can only re-code VA forms you initially coded."
    window = recode_window_for_submission(sid)
    window_start = sa.func.now() - window
    reviews_in_window = (
        db.session.execute(
            sa.select(VaCoderReview.va_sid
            ).where(
                (VaCoderReview.va_creview_by == user.user_id)
                & (VaCoderReview.va_sid == sid)
                # Tester output is never a coding of the case (digitva-ggc3).
                & VaCoderReview.is_tester.is_(False)
                & (VaCoderReview.va_creview_createdat > window_start)
            )
        )
        .mappings()
        .all()
    )
    finals_in_window = (
        db.session.execute(
            sa.select(
                VaFinalAssessments.va_sid
            ).where(
                (VaFinalAssessments.va_finassess_by == user.user_id)
                & (VaFinalAssessments.va_sid == sid)
                & VaFinalAssessments.is_tester.is_(False)
                & (VaFinalAssessments.va_finassess_createdat > window_start)
            )
        )
        .mappings()
        .all()
    )
    if len(reviews_in_window + finals_in_window) > 1:
        return (
            "You have already re-coded this VA form once in the last "
            f"{recode_window_label(window)}."
        )
    recent_final = db.session.scalars(
        sa.select(VaFinalAssessments.va_sid).where(
            (VaFinalAssessments.va_finassess_by == user.user_id)
            & (VaFinalAssessments.va_sid == sid)
            & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
            & (VaFinalAssessments.va_finassess_createdat > window_start)
        )
    ).all()
    recent_review = db.session.scalars(
        sa.select(VaCoderReview.va_sid).where(
            (VaCoderReview.va_creview_by == user.user_id)
            & (VaCoderReview.va_sid == sid)
            & (VaCoderReview.va_creview_status == VaStatuses.active)
            & (VaCoderReview.va_creview_createdat > window_start)
        )
    ).all()
    if sid not in recent_final + recent_review:
        return (
            f"Re-coding is only allowed within {recode_window_label(window)} "
            "of VA form finalisation."
        )
    return None
