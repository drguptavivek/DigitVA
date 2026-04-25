"""Reviewer-review artifact lifecycle policy."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaReviewerReview, VaStatuses
from app.services.coding.payload_artifacts.common import (
    add_artifact_audit,
    current_payload_version_id,
)


def get_current_payload_reviewer_review(
    va_sid: str,
    user_id,
) -> VaReviewerReview | None:
    """Return the active reviewer-review row for the submission's current payload."""
    active_payload_version_id = current_payload_version_id(va_sid)
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_rreview_id,
            audit_byrole=audit_byrole,
            audit_by=audit_by,
            audit_action=audit_action,
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_rreview_id,
            audit_byrole="vaadmin",
            audit_action="reviewer review promoted to current payload",
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_rreview_id,
            audit_byrole=audit_byrole,
            audit_by=audit_by,
            audit_action=audit_action,
        )
    return len(rows)
