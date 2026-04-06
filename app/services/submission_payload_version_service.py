"""Helpers for payload-version-aware ODK sync lineage."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
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


VOLATILE_PAYLOAD_KEYS = frozenset(
    {
        "AttachmentsExpected",
        "AttachmentsPresent",
        "DeviceID",
        "Edits",
        "FormVersion",
        "OdkReviewComments",
        "SubmitterID",
        "updatedAt",
        "audit",
        "instanceID",
        "survey_district",
        "survey_state",
        "ageInDays",
        "ageInDays2",
        "ageInDaysNeonate",
        "ageInMonths",
        "ageInMonthsByYear",
        "ageInMonthsRemain",
        "ageInYears",
        "ageInYears2",
        "ageInYearsRemain",
        "finalAgeInYears",
        "isAdult",
        "isAdult1",
        "isAdult2",
        "isChild",
        "isChild1",
        "isChild2",
        "isNeonatal",
        "isNeonatal1",
        "isNeonatal2",
    }
)

NULL_LIKE_STRING_VALUES = frozenset(
    {
        "",
        "na",
        "n/a",
        "none",
        "null",
    }
)


def _normalize_scalar(value):
    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return _canonicalize_numeric(value)

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.casefold() in NULL_LIKE_STRING_VALUES:
            return None
        try:
            return _canonicalize_numeric(stripped)
        except InvalidOperation:
            return stripped

    return value


def _canonicalize_numeric(value) -> str:
    normalized = Decimal(str(value)).normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def normalize_payload_for_fingerprint(payload_data: dict | list | object):
    """Return a stable business-payload representation for change detection."""
    if isinstance(payload_data, dict):
        return {
            key: normalize_payload_for_fingerprint(value)
            for key, value in payload_data.items()
            if key not in VOLATILE_PAYLOAD_KEYS
        }

    if isinstance(payload_data, list):
        return [normalize_payload_for_fingerprint(item) for item in payload_data]

    return _normalize_scalar(payload_data)


def canonical_payload_fingerprint(payload_data: dict) -> str:
    """Return a stable hash for full canonical normalized payload JSON."""
    canonical_json = json.dumps(
        normalize_payload_for_fingerprint(payload_data or {}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


_REQUIRED_METADATA_KEYS = (
    "FormVersion",
    "DeviceID",
    "SubmitterID",
    "instanceID",
    "AttachmentsExpected",
    "AttachmentsPresent",
)


def _derive_payload_metadata(payload_data: dict) -> tuple[bool, int | None]:
    """Return (has_required_metadata, attachments_expected) for a payload dict.

    has_required_metadata — True iff all six sync-completeness keys are present
    with non-None values in payload_data.

    attachments_expected — integer value of AttachmentsExpected, or None if
    absent, empty, or non-numeric.
    """
    has_meta = all(payload_data.get(k) is not None for k in _REQUIRED_METADATA_KEYS)
    raw = payload_data.get("AttachmentsExpected")
    att_expected: int | None = None
    if raw is not None:
        try:
            stripped = str(raw).strip()
            att_expected = int(stripped) if stripped else None
        except (ValueError, TypeError):
            att_expected = None
    return has_meta, att_expected


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

    if active and canonical_payload_fingerprint(active.payload_data or {}) == fingerprint:
        if submission.active_payload_version_id != active.payload_version_id:
            submission.active_payload_version_id = active.payload_version_id
        if source_updated_at is not None:
            active.source_updated_at = source_updated_at
        return active

    if active is None and submission.active_payload_version_id is not None:
        active = db.session.get(
            VaSubmissionPayloadVersion, submission.active_payload_version_id
        )
        if active and canonical_payload_fingerprint(active.payload_data or {}) == fingerprint:
            if source_updated_at is not None:
                active.source_updated_at = source_updated_at
            return active

    now = datetime.now(timezone.utc)
    if active is not None:
        active.version_status = PAYLOAD_VERSION_STATUS_SUPERSEDED
        active.superseded_at = now

    has_meta, att_expected = _derive_payload_metadata(payload_data)
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
        has_required_metadata=has_meta,
        attachments_expected=att_expected,
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
    if pending and canonical_payload_fingerprint(pending.payload_data or {}) == fingerprint:
        pending.payload_data = payload_data
        pending.source_updated_at = source_updated_at
        return pending

    now = datetime.now(timezone.utc)
    if pending is not None:
        pending.version_status = PAYLOAD_VERSION_STATUS_REJECTED
        pending.rejected_at = now
        pending.rejected_reason = "superseded_by_newer_pending_upstream_payload"

    has_meta, att_expected = _derive_payload_metadata(payload_data)
    version = VaSubmissionPayloadVersion(
        va_sid=submission.va_sid,
        source_updated_at=source_updated_at,
        payload_fingerprint=fingerprint,
        payload_data=payload_data,
        version_status=PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
        created_by_role=created_by_role,
        created_by=created_by,
        version_created_at=now,
        has_required_metadata=has_meta,
        attachments_expected=att_expected,
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
    has_meta, att_expected = _derive_payload_metadata(payload_data)
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
        has_required_metadata=has_meta,
        attachments_expected=att_expected,
    )
    db.session.add(version)
    db.session.flush()
    submission.active_payload_version_id = version.payload_version_id
    return version
