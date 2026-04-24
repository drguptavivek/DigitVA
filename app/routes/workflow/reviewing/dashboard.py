"""Reviewer dashboard route."""

import sqlalchemy as sa
from flask import render_template
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.models import (
    VaAllocation,
    VaAllocations,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.utils import va_render_serialisedates

from .common import reviewing


@reviewing.get("/")
@action_authorized("reviewing_dashboard_view")
def dashboard():
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
        va_forms_completed = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaReviewerFinalAssessments)
            .where(
                VaReviewerFinalAssessments.va_rfinassess_by == current_user.user_id,
                VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
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
                    sa.case(
                        (
                            VaSubmissionWorkflow.workflow_state
                            == "reviewer_finalized",
                            sa.literal("Reviewed"),
                        ),
                        (
                            VaSubmissionWorkflow.workflow_state
                            == "reviewer_coding_in_progress",
                            sa.literal("In Progress"),
                        ),
                        else_=sa.literal("Not Reviewed"),
                    ).label("va_review_status"),
                    sa.func.date(
                        VaReviewerFinalAssessments.va_rfinassess_createdat
                    ).label("va_reviewed_at"),
                )
                .outerjoin(
                    VaSubmissionWorkflow,
                    VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
                )
                .outerjoin(
                    VaReviewerFinalAssessments,
                    sa.and_(
                        VaReviewerFinalAssessments.va_sid == VaSubmissions.va_sid,
                        VaReviewerFinalAssessments.va_rfinassess_status
                        == VaStatuses.active,
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
