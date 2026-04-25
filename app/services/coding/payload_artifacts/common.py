"""Shared current-payload and audit helpers for coding artifacts."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.submissions.payload_version import get_active_payload_version


def get_submission_with_current_payload(
    va_sid: str,
    *,
    for_update: bool = False,
) -> tuple[VaSubmissions, VaSubmissionPayloadVersion]:
    """Return the submission and ensure it has an active payload version."""
    stmt = sa.select(VaSubmissions).where(VaSubmissions.va_sid == va_sid)
    if for_update:
        stmt = stmt.with_for_update()
    submission = db.session.scalar(stmt)
    if submission is None:
        raise ValueError("Submission not found.")

    active_payload_version = get_active_payload_version(va_sid)
    if active_payload_version is None:
        raise ValueError("Submission has no active payload version.")
    return submission, active_payload_version


def current_payload_version_id(va_sid: str):
    """Return the submission's active payload version id, or None."""
    return db.session.scalar(
        sa.select(VaSubmissions.active_payload_version_id).where(
            VaSubmissions.va_sid == va_sid
        )
    )


def add_artifact_audit(
    *,
    va_sid: str,
    entity_id,
    audit_byrole: str,
    audit_action: str,
    audit_by=None,
) -> None:
    """Record an audit event for a coding artifact lifecycle change."""
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_entityid=entity_id,
            va_audit_byrole=audit_byrole,
            va_audit_by=audit_by,
            va_audit_operation="u",
            va_audit_action=audit_action,
        )
    )
