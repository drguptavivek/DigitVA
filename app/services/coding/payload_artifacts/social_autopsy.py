"""Social Autopsy analysis artifact lifecycle policy."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaSocialAutopsyAnalysis, VaStatuses
from app.services.coding.payload_artifacts.common import (
    add_artifact_audit,
    current_payload_version_id,
)


def get_current_payload_social_autopsy_analysis(
    va_sid: str,
    user_id,
) -> VaSocialAutopsyAnalysis | None:
    """Return the active Social Autopsy row for the submission's current payload."""
    active_payload_version_id = current_payload_version_id(va_sid)
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_saa_id,
            audit_byrole=audit_byrole,
            audit_by=audit_by,
            audit_action=audit_action,
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_saa_id,
            audit_byrole="vaadmin",
            audit_action="social autopsy analysis promoted to current payload",
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
        add_artifact_audit(
            va_sid=va_sid,
            entity_id=row.va_saa_id,
            audit_byrole=audit_byrole,
            audit_by=audit_by,
            audit_action=audit_action,
        )
    return len(rows)
