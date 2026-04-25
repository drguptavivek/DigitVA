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


def create_reviewer_final_assessment(
    *,
    va_sid: str,
    reviewer_user_id,
    conclusive_cod: str,
    remark: str | None = None,
    supersedes_coder_final_assessment: VaFinalAssessments | None = None,
) -> VaReviewerFinalAssessments:
    """Create a reviewer-owned final COD row for a submission."""
    if supersedes_coder_final_assessment is not None:
        if supersedes_coder_final_assessment.va_sid != va_sid:
            raise ValueError(
                "supersedes_coder_final_assessment must belong to the same submission."
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
    )
    db.session.add(reviewer_final)
    return reviewer_final
