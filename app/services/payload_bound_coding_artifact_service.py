"""Helpers for coding artifacts that must follow the current payload version."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    VaNarrativeAssessment,
    VaReviewerReview,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.submission_payload_version_service import ensure_active_payload_version


def get_submission_with_current_payload(
    va_sid: str,
    *,
    for_update: bool = False,
    created_by_role: str = "vasystem",
    created_by=None,
) -> tuple[VaSubmissions, VaSubmissionPayloadVersion]:
    """Return the submission and ensure it has an active payload version."""
    stmt = sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_sid)
    if for_update:
        stmt = stmt.with_for_update()
    submission = db.session.scalar(stmt)
    if submission is None:
        raise ValueError("Submission not found.")

    active_payload_version = ensure_active_payload_version(
        submission,
        payload_data=submission.va_data or {},
        source_updated_at=submission.va_odk_updatedat,
        created_by_role=created_by_role,
        created_by=created_by,
    )
    return submission, active_payload_version


def get_current_payload_narrative_assessment(
    va_sid: str,
    user_id,
) -> VaNarrativeAssessment | None:
    """Return the active NQA row for the submission's current payload."""
    active_payload_version_id = db.session.scalar(
        sa.select(VaSubmissions.active_payload_version_id).where(
            VaSubmissions.va_sid == va_sid
        )
    )
    if active_payload_version_id is None:
        return None

    return db.session.scalar(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_sid == va_sid,
            VaNarrativeAssessment.va_nqa_by == user_id,
            VaNarrativeAssessment.payload_version_id == active_payload_version_id,
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
        )
    )


def get_current_payload_reviewer_review(
    va_sid: str,
    user_id,
) -> VaReviewerReview | None:
    """Return the active reviewer-review row for the submission's current payload."""
    active_payload_version_id = db.session.scalar(
        sa.select(VaSubmissions.active_payload_version_id).where(
            VaSubmissions.va_sid == va_sid
        )
    )
    if active_payload_version_id is None:
        return None

    return db.session.scalar(
        sa.select(VaReviewerReview).where(
            VaReviewerReview.va_sid == va_sid,
            VaReviewerReview.va_rreview_by == user_id,
            VaReviewerReview.payload_version_id == active_payload_version_id,
            VaReviewerReview.va_rreview_status == VaStatuses.active,
        )
    )


def get_current_payload_social_autopsy_analysis(
    va_sid: str,
    user_id,
) -> VaSocialAutopsyAnalysis | None:
    """Return the active Social Autopsy row for the submission's current payload."""
    active_payload_version_id = db.session.scalar(
        sa.select(VaSubmissions.active_payload_version_id).where(
            VaSubmissions.va_sid == va_sid
        )
    )
    if active_payload_version_id is None:
        return None

    return db.session.scalar(
        sa.select(VaSocialAutopsyAnalysis).where(
            VaSocialAutopsyAnalysis.va_sid == va_sid,
            VaSocialAutopsyAnalysis.va_saa_by == user_id,
            VaSocialAutopsyAnalysis.payload_version_id == active_payload_version_id,
            VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
        )
    )


def deactivate_other_active_narrative_assessments(
    va_sid: str,
    user_id,
    *,
    keep_id=None,
    audit_byrole: str = "vacoder",
    audit_by=None,
    audit_action: str = "narrative quality assessment superseded by current payload",
) -> int:
    """Deactivate other active NQA rows for the same submission/user."""
    stmt = sa.select(VaNarrativeAssessment).where(
        VaNarrativeAssessment.va_sid == va_sid,
        VaNarrativeAssessment.va_nqa_by == user_id,
        VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
    )
    if keep_id is not None:
        stmt = stmt.where(VaNarrativeAssessment.va_nqa_id != keep_id)

    rows = db.session.scalars(stmt).all()
    for row in rows:
        row.va_nqa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_nqa_id,
                va_audit_byrole=audit_byrole,
                va_audit_by=audit_by,
                va_audit_operation="u",
                va_audit_action=audit_action,
            )
        )
    return len(rows)


def deactivate_other_active_reviewer_reviews(
    va_sid: str,
    user_id,
    *,
    keep_id=None,
    audit_byrole: str = "reviewer",
    audit_by=None,
    audit_action: str = "reviewer review superseded by current payload",
) -> int:
    """Deactivate other active reviewer-review rows for the same submission/user."""
    stmt = sa.select(VaReviewerReview).where(
        VaReviewerReview.va_sid == va_sid,
        VaReviewerReview.va_rreview_by == user_id,
        VaReviewerReview.va_rreview_status == VaStatuses.active,
    )
    if keep_id is not None:
        stmt = stmt.where(VaReviewerReview.va_rreview_id != keep_id)

    rows = db.session.scalars(stmt).all()
    for row in rows:
        row.va_rreview_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_rreview_id,
                va_audit_byrole=audit_byrole,
                va_audit_by=audit_by,
                va_audit_operation="u",
                va_audit_action=audit_action,
            )
        )
    return len(rows)


def deactivate_other_active_social_autopsy_analyses(
    va_sid: str,
    user_id,
    *,
    keep_id=None,
    audit_byrole: str = "vacoder",
    audit_by=None,
    audit_action: str = "social autopsy analysis superseded by current payload",
) -> int:
    """Deactivate other active Social Autopsy rows for the same submission/user."""
    stmt = sa.select(VaSocialAutopsyAnalysis).where(
        VaSocialAutopsyAnalysis.va_sid == va_sid,
        VaSocialAutopsyAnalysis.va_saa_by == user_id,
        VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
    )
    if keep_id is not None:
        stmt = stmt.where(VaSocialAutopsyAnalysis.va_saa_id != keep_id)

    rows = db.session.scalars(stmt).all()
    for row in rows:
        row.va_saa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_saa_id,
                va_audit_byrole=audit_byrole,
                va_audit_by=audit_by,
                va_audit_operation="u",
                va_audit_action=audit_action,
            )
        )
    return len(rows)


def promote_active_narrative_assessments_to_payload(
    va_sid: str,
    *,
    to_payload_version_id,
) -> int:
    """Rebind active NQA rows to a promoted payload version."""
    rows = db.session.scalars(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_sid == va_sid,
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
        )
    ).all()
    for row in rows:
        row.payload_version_id = to_payload_version_id
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_nqa_id,
                va_audit_byrole="vaadmin",
                va_audit_operation="u",
                va_audit_action="narrative quality assessment promoted to current payload",
            )
        )
    return len(rows)


def promote_active_reviewer_reviews_to_payload(
    va_sid: str,
    *,
    to_payload_version_id,
) -> int:
    """Rebind active reviewer-review rows to a promoted payload version."""
    rows = db.session.scalars(
        sa.select(VaReviewerReview).where(
            VaReviewerReview.va_sid == va_sid,
            VaReviewerReview.va_rreview_status == VaStatuses.active,
        )
    ).all()
    for row in rows:
        row.payload_version_id = to_payload_version_id
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_rreview_id,
                va_audit_byrole="vaadmin",
                va_audit_operation="u",
                va_audit_action="reviewer review promoted to current payload",
            )
        )
    return len(rows)


def promote_active_social_autopsy_analyses_to_payload(
    va_sid: str,
    *,
    to_payload_version_id,
) -> int:
    """Rebind active Social Autopsy rows to a promoted payload version."""
    rows = db.session.scalars(
        sa.select(VaSocialAutopsyAnalysis).where(
            VaSocialAutopsyAnalysis.va_sid == va_sid,
            VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
        )
    ).all()
    for row in rows:
        row.payload_version_id = to_payload_version_id
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_saa_id,
                va_audit_byrole="vaadmin",
                va_audit_operation="u",
                va_audit_action="social autopsy analysis promoted to current payload",
            )
        )
    return len(rows)


def deactivate_active_reviewer_reviews_for_submission(
    va_sid: str,
    *,
    audit_byrole: str = "vaadmin",
    audit_by=None,
    audit_action: str = "reviewer review deactivated due to payload change",
) -> int:
    """Deactivate all active reviewer-review rows for a submission."""
    rows = db.session.scalars(
        sa.select(VaReviewerReview).where(
            VaReviewerReview.va_sid == va_sid,
            VaReviewerReview.va_rreview_status == VaStatuses.active,
        )
    ).all()
    for row in rows:
        row.va_rreview_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_rreview_id,
                va_audit_byrole=audit_byrole,
                va_audit_by=audit_by,
                va_audit_operation="u",
                va_audit_action=audit_action,
            )
        )
    return len(rows)


def deactivate_active_narrative_assessments_for_submission(
    va_sid: str,
    *,
    audit_byrole: str = "vaadmin",
    audit_by=None,
    audit_action: str = "narrative quality assessment deactivated due to payload change",
) -> int:
    """Deactivate all active NQA rows for a submission."""
    rows = db.session.scalars(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_sid == va_sid,
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
        )
    ).all()
    for row in rows:
        row.va_nqa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_nqa_id,
                va_audit_byrole=audit_byrole,
                va_audit_by=audit_by,
                va_audit_operation="u",
                va_audit_action=audit_action,
            )
        )
    return len(rows)


def deactivate_active_social_autopsy_analyses_for_submission(
    va_sid: str,
    *,
    audit_byrole: str = "vaadmin",
    audit_by=None,
    audit_action: str = "social autopsy analysis deactivated due to payload change",
) -> int:
    """Deactivate all active Social Autopsy rows for a submission."""
    rows = db.session.scalars(
        sa.select(VaSocialAutopsyAnalysis).where(
            VaSocialAutopsyAnalysis.va_sid == va_sid,
            VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
        )
    ).all()
    for row in rows:
        row.va_saa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_saa_id,
                va_audit_byrole=audit_byrole,
                va_audit_by=audit_by,
                va_audit_operation="u",
                va_audit_action=audit_action,
            )
        )
    return len(rows)
