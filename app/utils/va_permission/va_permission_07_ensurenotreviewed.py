import sqlalchemy as sa
from app import db
from flask_login import current_user
from flask import redirect, url_for, flash
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash
from app.models import (
    VaAllocations,
    VaAllocation,
    VaCoderReview,
    VaFinalAssessments,
    VaStatuses,
    VaSubmissionWorkflow,
)


def va_permission_ensurenotreviewed(sid):
    # Use canonical workflow state as the primary signal.
    # reviewer_finalized     → terminal, block re-start
    # reviewer_coding_in_progress → session active, redirect or block
    # NQA (VaReviewerReview) and Social Autopsy are supporting artifacts — their
    # presence alone does not block a new reviewer session.
    workflow_state = db.session.scalar(
        sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == sid
        )
    )
    coded1 = db.session.scalar(
        sa.select(VaCoderReview.va_sid).where(
            (VaCoderReview.va_sid == sid)
            & (VaCoderReview.va_creview_status == VaStatuses.active)
        )
    )
    coded2 = db.session.scalar(
        sa.select(VaFinalAssessments.va_sid).where(
            (VaFinalAssessments.va_sid == sid)
            & (VaFinalAssessments.va_finassess_status == VaStatuses.active)
        )
    )
    if workflow_state == "reviewer_finalized":
        va_permission_abortwithflash("This VA form has already been reviewed.", 403)
    if coded1 or coded2:
        va_permission_abortwithflash("This VA form has already been coded.", 403)
    if workflow_state == "reviewer_coding_in_progress":
        alloc = db.session.scalar(
            sa.select(VaAllocations.va_allocated_to).where(
                (VaAllocations.va_sid == sid)
                & (VaAllocations.va_allocation_status == VaStatuses.active)
                & (VaAllocations.va_allocation_for == VaAllocation.reviewing)
            )
        )
        if alloc and current_user.user_id == alloc:
            return redirect(url_for("reviewing.resume"))
        if alloc:
            flash(
                "This VA form is already allocated to someone for the review. Please select again."
            )
            return redirect(url_for("reviewing.dashboard"))