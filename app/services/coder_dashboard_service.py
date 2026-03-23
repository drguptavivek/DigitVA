"""Coder dashboard queries backed by canonical workflow state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app import db
from app.models import (
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
)
from app.utils import va_render_serialisedates


CODER_COMPLETED_WORKFLOW_STATES = (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
)


def get_coder_completed_count(user_id, accessible_form_ids: Sequence[str]) -> int:
    """Return the number of coder-completed submissions visible to this coder."""
    if not accessible_form_ids:
        return 0

    return db.session.scalar(
        sa.select(sa.func.count())
        .select_from(VaSubmissions)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(
            VaFinalAssessments,
            sa.and_(
                VaFinalAssessments.va_sid == VaSubmissions.va_sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
                VaFinalAssessments.va_finassess_by == user_id,
            ),
        )
        .outerjoin(
            VaCoderReview,
            sa.and_(
                VaCoderReview.va_sid == VaSubmissions.va_sid,
                VaCoderReview.va_creview_status == VaStatuses.active,
                VaCoderReview.va_creview_by == user_id,
            ),
        )
        .where(
            VaSubmissions.va_form_id.in_(accessible_form_ids),
            VaSubmissionWorkflow.workflow_state.in_(CODER_COMPLETED_WORKFLOW_STATES),
            sa.or_(
                VaFinalAssessments.va_finassess_id.is_not(None),
                VaCoderReview.va_creview_id.is_not(None),
            ),
        )
    ) or 0


def get_coder_completed_history(user_id, accessible_form_ids: Sequence[str]) -> list[dict]:
    """Return coder history rows using canonical workflow state as the source of truth."""
    if not accessible_form_ids:
        return []

    stmt = (
        sa.select(
            sa.func.date(VaSubmissions.va_submission_date).label("va_submission_date"),
            VaSubmissions.va_form_id,
            VaSubmissions.va_sid,
            VaSubmissions.va_uniqueid_masked,
            VaSubmissions.va_data_collector,
            VaSubmissions.va_deceased_age,
            VaSubmissions.va_deceased_gender,
            sa.case(
                (
                    VaSubmissionWorkflow.workflow_state == WORKFLOW_CODER_FINALIZED,
                    VaFinalAssessments.va_finassess_createdat,
                ),
                else_=VaCoderReview.va_creview_createdat,
            ).label("va_coding_date"),
            sa.case(
                (
                    VaSubmissionWorkflow.workflow_state == WORKFLOW_CODER_FINALIZED,
                    sa.literal("VA Coding Completed"),
                ),
                else_=sa.literal("Not Codeable"),
            ).label("va_code_status"),
        )
        .select_from(VaSubmissions)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(
            VaFinalAssessments,
            sa.and_(
                VaFinalAssessments.va_sid == VaSubmissions.va_sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
                VaFinalAssessments.va_finassess_by == user_id,
            ),
        )
        .outerjoin(
            VaCoderReview,
            sa.and_(
                VaCoderReview.va_sid == VaSubmissions.va_sid,
                VaCoderReview.va_creview_status == VaStatuses.active,
                VaCoderReview.va_creview_by == user_id,
            ),
        )
        .where(
            VaSubmissions.va_form_id.in_(accessible_form_ids),
            VaSubmissionWorkflow.workflow_state.in_(CODER_COMPLETED_WORKFLOW_STATES),
            sa.or_(
                sa.and_(
                    VaSubmissionWorkflow.workflow_state == WORKFLOW_CODER_FINALIZED,
                    VaFinalAssessments.va_finassess_id.is_not(None),
                ),
                sa.and_(
                    VaSubmissionWorkflow.workflow_state == WORKFLOW_NOT_CODEABLE_BY_CODER,
                    VaCoderReview.va_creview_id.is_not(None),
                ),
            ),
        )
        .order_by(sa.desc("va_coding_date"), sa.desc(VaSubmissions.va_submission_date))
    )

    rows = db.session.execute(stmt).mappings().all()
    return [
        va_render_serialisedates(row, ["va_submission_date", "va_coding_date"])
        for row in rows
    ]


def get_coder_recodeable_sids(user_id, accessible_form_ids: Sequence[str]) -> list[str]:
    """Return recently finalized SIDs that are eligible for recode."""
    if not accessible_form_ids:
        return []

    recent_window = sa.text("interval '24 hours'")
    stmt = (
        sa.select(VaSubmissions.va_sid)
        .select_from(VaSubmissions)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .outerjoin(
            VaFinalAssessments,
            sa.and_(
                VaFinalAssessments.va_sid == VaSubmissions.va_sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
                VaFinalAssessments.va_finassess_by == user_id,
            ),
        )
        .outerjoin(
            VaCoderReview,
            sa.and_(
                VaCoderReview.va_sid == VaSubmissions.va_sid,
                VaCoderReview.va_creview_status == VaStatuses.active,
                VaCoderReview.va_creview_by == user_id,
            ),
        )
        .where(
            VaSubmissions.va_form_id.in_(accessible_form_ids),
            VaSubmissionWorkflow.workflow_state == WORKFLOW_CODER_FINALIZED,
            VaFinalAssessments.va_finassess_id.is_not(None),
            VaFinalAssessments.va_finassess_createdat + recent_window
            > sa.func.now(),
            VaCoderReview.va_creview_id.is_(None),
        )
    )
    return db.session.scalars(stmt).all()


def get_coder_project_ids(accessible_form_ids: Sequence[str]) -> list[str]:
    """Return distinct project IDs for the supplied form set."""
    if not accessible_form_ids:
        return []

    return db.session.execute(
        sa.select(VaForms.project_id)
        .where(VaForms.form_id.in_(accessible_form_ids))
        .distinct()
        .order_by(VaForms.project_id)
    ).scalars().all()
