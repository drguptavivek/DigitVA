"""Narrative Quality Assessment artifact lifecycle policy."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaNarrativeAssessment, VaStatuses
from app.services.coding.payload_artifacts.common import (
    add_artifact_audit,
    current_payload_version_id,
)


def get_current_payload_narrative_assessment(
    va_sid: str,
    user_id,
) -> VaNarrativeAssessment | None:
    """Return the active NQA row for the submission's current payload."""
    active_payload_version_id = current_payload_version_id(va_sid)
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_nqa_id,
            audit_byrole=audit_byrole,
            audit_by=audit_by,
            audit_action=audit_action,
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_nqa_id,
            audit_byrole="vaadmin",
            audit_action="narrative quality assessment promoted to current payload",
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_nqa_id,
            audit_byrole=audit_byrole,
            audit_by=audit_by,
            audit_action=audit_action,
        )
    return len(rows)
