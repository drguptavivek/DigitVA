"""Enrolled collection devices and their interviewer sessions (Path B).

Baseline: docs/policy/field-data-collection.md ("Path B design"); design
record .tasks/2026-09-30-android-collection-app.md. Every credential here
(enrolment code, device secret, access and refresh token) is a 256-bit
random value stored only as its SHA-256 hex digest; the plaintext is shown
to its holder once. Rules live in app/services/device_auth_service.py.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


def _utcnow():
    return datetime.now(UTC)


class AuthDeviceEnrolmentCode(db.Model):
    """A one-time (or few-time) code an admin issues to enrol devices into one project."""

    __tablename__ = "auth_device_enrolment_codes"

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False, index=True
    )
    code_hash: so.Mapped[str] = so.mapped_column(sa.String(64), unique=True, nullable=False)
    expires_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    max_uses: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False, default=1)
    use_count: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    created_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    revoked_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuthDevice(db.Model):
    """A handset enrolled into one project. Shared by interviewers (decision C2)."""

    __tablename__ = "auth_devices"

    device_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False, index=True
    )
    name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    platform: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    app_version: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    secret_hash: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    enrolled_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    enrolled_via: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_device_enrolment_codes.id"), nullable=True
    )
    revoked_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    last_seen_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuthDeviceSession(db.Model):
    """One interviewer signed in on one device: an access and a refresh token.

    ``previous_refresh_hash`` is the refresh token this row rotated away from
    last; presenting it again is reuse and revokes the session. The
    ``outstanding_*`` columns are the device's last report of unsent
    interviews for this interviewer (policy: outstanding work visible
    server-side).
    """

    __tablename__ = "auth_device_sessions"

    session_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_devices.device_id"), nullable=False, index=True
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False, index=True
    )
    access_hash: so.Mapped[str] = so.mapped_column(sa.String(64), unique=True, nullable=False)
    access_expires_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    refresh_hash: so.Mapped[str] = so.mapped_column(sa.String(64), unique=True, nullable=False)
    refresh_expires_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    # The user's auth_session_version when the session opened: a password or
    # factor reset bumps it and so ends device sessions too.
    user_session_version: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    previous_refresh_hash: so.Mapped[str | None] = so.mapped_column(
        sa.String(64), nullable=True, index=True
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_reason: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    outstanding_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    outstanding_unique_ids: so.Mapped[list | None] = so.mapped_column(JSONB, nullable=True)
    outstanding_reported_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
