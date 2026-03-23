"""Helpers for payload-version-aware ODK sync lineage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import VaSubmissionPayloadVersion, VaSubmissions
from app.models.va_submission_payload_versions import (
    PAYLOAD_VERSION_STATUS_ACTIVE,
    PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
    PAYLOAD_VERSION_STATUS_REJECTED,
    PAYLOAD_VERSION_STATUS_SUPERSEDED,
)


def canonical_payload_fingerprint(payload_data: dict) -> str:
    """Return a stable hash for full canonical normalized payload JSON."""
    canonical_json = json.dumps(
        payload_data or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def get_active_payload_version(va_sid: str) -> VaSubmissionPayloadVersion | None:
    return db.session.scalar(
        sa.select(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == va_sid,
            VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
        )
    )


def get_latest_pending_upstream_payload_version(
    va_sid: str,
) -> VaSubmissionPayloadVersion | None:
    return db.session.scalar(
        sa.select(VaSubmissionPayloadVersion)
        .where(
            VaSubmissionPayloadVersion.va_sid == va_sid,
            VaSubmissionPayloadVersion.version_status
            == PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
        )
        .order_by(VaSubmissionPayloadVersion.version_created_at.desc())
    )


def get_payload_version(
    payload_version_id,
) -> VaSubmissionPayloadVersion | None:
    if payload_version_id is None:
        return None
    return db.session.get(VaSubmissionPayloadVersion, payload_version_id)


def ensure_active_payload_version(
    submission: VaSubmissions,
    *,
    payload_data: dict,
    source_updated_at=None,
    created_by_role: str = "vasystem",
    created_by=None,
) -> VaSubmissionPayloadVersion:
    """Ensure a submission has an active payload version matching payload_data."""
    active = get_active_payload_version(submission.va_sid)
    fingerprint = canonical_payload_fingerprint(payload_data)

    if active and active.payload_fingerprint == fingerprint:
        if submission.active_payload_version_id != active.payload_version_id:
            submission.active_payload_version_id = active.payload_version_id
        if source_updated_at is not None:
            active.source_updated_at = source_updated_at
        return active

    if active is None and submission.active_payload_version_id is not None:
        active = db.session.get(
            VaSubmissionPayloadVersion, submission.active_payload_version_id
        )
        if active and active.payload_fingerprint == fingerprint:
            if source_updated_at is not None:
                active.source_updated_at = source_updated_at
            return active

    if active is None and submission.va_data:
        seeded = _bootstrap_active_payload_version(
            submission,
            payload_data=submission.va_data,
            source_updated_at=submission.va_odk_updatedat,
            created_by_role=created_by_role,
            created_by=created_by,
        )
        if seeded.payload_fingerprint == fingerprint:
            return seeded
        active = seeded

    now = datetime.now(timezone.utc)
    if active is not None:
        active.version_status = PAYLOAD_VERSION_STATUS_SUPERSEDED
        active.superseded_at = now

    version = VaSubmissionPayloadVersion(
        va_sid=submission.va_sid,
        source_updated_at=source_updated_at,
        payload_fingerprint=fingerprint,
        payload_data=payload_data,
        version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
        created_by_role=created_by_role,
        created_by=created_by,
        version_created_at=now,
        version_activated_at=now,
    )
    db.session.add(version)
    db.session.flush()
    submission.active_payload_version_id = version.payload_version_id
    return version


def create_or_update_pending_upstream_payload_version(
    submission: VaSubmissions,
    *,
    payload_data: dict,
    source_updated_at=None,
    created_by_role: str = "vasystem",
    created_by=None,
) -> VaSubmissionPayloadVersion:
    """Create or update the pending upstream payload version for a protected submission."""
    fingerprint = canonical_payload_fingerprint(payload_data)
    pending = get_latest_pending_upstream_payload_version(submission.va_sid)
    if pending and pending.payload_fingerprint == fingerprint:
        pending.payload_data = payload_data
        pending.source_updated_at = source_updated_at
        return pending

    now = datetime.now(timezone.utc)
    if pending is not None:
        pending.version_status = PAYLOAD_VERSION_STATUS_REJECTED
        pending.rejected_at = now
        pending.rejected_reason = "superseded_by_newer_pending_upstream_payload"

    version = VaSubmissionPayloadVersion(
        va_sid=submission.va_sid,
        source_updated_at=source_updated_at,
        payload_fingerprint=fingerprint,
        payload_data=payload_data,
        version_status=PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
        created_by_role=created_by_role,
        created_by=created_by,
        version_created_at=now,
    )
    db.session.add(version)
    db.session.flush()
    return version


def promote_pending_upstream_payload_version(
    submission: VaSubmissions,
    pending_version: VaSubmissionPayloadVersion,
) -> VaSubmissionPayloadVersion:
    """Promote a pending upstream payload version to active."""
    if pending_version.version_status != PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM:
        raise ValueError("Payload version is not pending_upstream.")

    now = datetime.now(timezone.utc)
    active = get_active_payload_version(submission.va_sid)
    if active is not None and active.payload_version_id != pending_version.payload_version_id:
        active.version_status = PAYLOAD_VERSION_STATUS_SUPERSEDED
        active.superseded_at = now
        db.session.flush()

    pending_version.version_status = PAYLOAD_VERSION_STATUS_ACTIVE
    pending_version.version_activated_at = now
    pending_version.rejected_at = None
    pending_version.rejected_reason = None
    submission.active_payload_version_id = pending_version.payload_version_id
    return pending_version


def reject_pending_upstream_payload_version(
    pending_version: VaSubmissionPayloadVersion,
    *,
    reason: str,
) -> VaSubmissionPayloadVersion:
    """Mark a pending upstream payload version as rejected."""
    if pending_version.version_status != PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM:
        raise ValueError("Payload version is not pending_upstream.")

    pending_version.version_status = PAYLOAD_VERSION_STATUS_REJECTED
    pending_version.rejected_at = datetime.now(timezone.utc)
    pending_version.rejected_reason = reason
    return pending_version


def _bootstrap_active_payload_version(
    submission: VaSubmissions,
    *,
    payload_data: dict,
    source_updated_at=None,
    created_by_role: str,
    created_by,
) -> VaSubmissionPayloadVersion:
    now = datetime.now(timezone.utc)
    version = VaSubmissionPayloadVersion(
        va_sid=submission.va_sid,
        source_updated_at=source_updated_at,
        payload_fingerprint=canonical_payload_fingerprint(payload_data),
        payload_data=payload_data,
        version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
        created_by_role=created_by_role,
        created_by=created_by,
        version_created_at=now,
        version_activated_at=now,
    )
    db.session.add(version)
    db.session.flush()
    submission.active_payload_version_id = version.payload_version_id
    return version
