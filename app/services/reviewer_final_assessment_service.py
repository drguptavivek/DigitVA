"""Reviewer final-COD artifact helpers.

This module introduces the reviewer-owned final COD artifact without yet
changing authoritative final-COD precedence. Authority cutover happens in a
later slice once reviewer submission flow is implemented end-to-end.
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    VaFinalAssessments,
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaStatuses,
    VaSubmissions,
)


def get_latest_active_reviewer_final_assessment(
    va_sid: str,
) -> VaReviewerFinalAssessments | None:
    """Return the latest active reviewer final-COD row for a submission."""
    return db.session.scalar(
        db.select(VaReviewerFinalAssessments)
        .where(
            VaReviewerFinalAssessments.va_sid == va_sid,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
        .order_by(VaReviewerFinalAssessments.va_rfinassess_createdat.desc())
    )


def get_latest_active_reviewer_initial_assessment(
    va_sid: str,
    reviewer_user_id=None,
) -> VaReviewerInitialAssessments | None:
    """Return the latest active reviewer initial-COD row for a submission."""
    filters = [
        VaReviewerInitialAssessments.va_sid == va_sid,
        VaReviewerInitialAssessments.va_riniassess_status == VaStatuses.active,
    ]
    if reviewer_user_id is not None:
        filters.append(
            VaReviewerInitialAssessments.va_riniassess_by == reviewer_user_id
        )
    return db.session.scalar(
        db.select(VaReviewerInitialAssessments)
        .where(*filters)
        .order_by(VaReviewerInitialAssessments.va_riniassess_createdat.desc())
    )


def create_reviewer_initial_assessment(
    *,
    va_sid: str,
    reviewer_user_id,
    immediate_cod: str,
    antecedent_cod: str,
    other_conditions: str | None = None,
) -> VaReviewerInitialAssessments:
    """Create a reviewer-owned initial COD row for a submission."""
    active_payload_version_id = db.session.scalar(
        sa.select(VaSubmissions.active_payload_version_id).where(
            VaSubmissions.va_sid == va_sid
        )
    )
    if active_payload_version_id is None:
        raise ValueError("Submission has no active payload version.")

    for existing in db.session.scalars(
        sa.select(VaReviewerInitialAssessments).where(
            VaReviewerInitialAssessments.va_sid == va_sid,
            VaReviewerInitialAssessments.va_riniassess_by == reviewer_user_id,
            VaReviewerInitialAssessments.payload_version_id
            == active_payload_version_id,
            VaReviewerInitialAssessments.va_riniassess_status == VaStatuses.active,
        )
    ).all():
        existing.va_riniassess_status = VaStatuses.deactive

    reviewer_initial = VaReviewerInitialAssessments(
        va_sid=va_sid,
        payload_version_id=active_payload_version_id,
        va_riniassess_by=reviewer_user_id,
        va_immediate_cod=immediate_cod,
        va_antecedent_cod=antecedent_cod,
        va_other_conditions=other_conditions,
    )
    db.session.add(reviewer_initial)
    return reviewer_initial


def create_reviewer_final_assessment(
    *,
    va_sid: str,
    reviewer_user_id,
    conclusive_cod: str,
    remark: str | None = None,
    supersedes_coder_final_assessment: VaFinalAssessments | None = None,
    source_reviewer_initial_assessment: VaReviewerInitialAssessments | None = None,
) -> VaReviewerFinalAssessments:
    """Create a reviewer-owned final COD row for a submission."""
    if supersedes_coder_final_assessment is not None:
        if supersedes_coder_final_assessment.va_sid != va_sid:
            raise ValueError(
                "supersedes_coder_final_assessment must belong to the same submission."
            )
    if source_reviewer_initial_assessment is not None:
        if source_reviewer_initial_assessment.va_sid != va_sid:
            raise ValueError(
                "source_reviewer_initial_assessment must belong to the same submission."
            )

    active_payload_version_id = db.session.scalar(
        sa.select(VaSubmissions.active_payload_version_id).where(
            VaSubmissions.va_sid == va_sid
        )
    )
    if active_payload_version_id is None:
        raise ValueError("Submission has no active payload version.")

    reviewer_final = VaReviewerFinalAssessments(
        va_sid=va_sid,
        payload_version_id=active_payload_version_id,
        va_rfinassess_by=reviewer_user_id,
        va_conclusive_cod=conclusive_cod,
        va_rfinassess_remark=remark,
        supersedes_coder_final_assessment_id=(
            supersedes_coder_final_assessment.va_finassess_id
            if supersedes_coder_final_assessment
            else None
        ),
        source_reviewer_initial_assessment_id=(
            source_reviewer_initial_assessment.va_riniassess_id
            if source_reviewer_initial_assessment
            else None
        ),
    )
    db.session.add(reviewer_final)
    return reviewer_final
