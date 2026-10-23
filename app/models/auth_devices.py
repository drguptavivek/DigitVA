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
    # Set instead of ``enrolled_via`` when a sign-in QR enrolled the device
    # (mobile-sign-in.md section 8): the token row, not an enrolment code.
    enrolled_via_sign_in_token: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_sign_in_tokens.id", name="fk_auth_devices_enrolled_via_sign_in_token", use_alter=True),
        nullable=True
    )
    revoked_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    last_seen_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    # A lost or stolen device: every bundle it signed is refused, not only
    # those created after revoked_at (docs/policy/offline-bundle-and-transfer.md 3.2).
    revoked_compromised: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    # The current Ed25519 bundle-signing key, raw 32 bytes; every key it has
    # held, this one included, is in auth_device_signing_keys.
    signing_public_key: so.Mapped[bytes | None] = so.mapped_column(sa.LargeBinary, nullable=True)
    signing_key_id: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True, index=True)
    signing_key_set_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuthDeviceSigningKey(db.Model):
    """Every Ed25519 signing key a device has held, so a bundle signed before
    a re-key still verifies. The current key has ``retired_at`` NULL.
    Rules: app/services/device_signing_service.py."""

    __tablename__ = "auth_device_signing_keys"
    __table_args__ = (
        sa.UniqueConstraint("device_id", "signing_key_id", name="uq_auth_device_signing_keys_device_key"),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    device_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_devices.device_id"), nullable=False
    )
    signing_public_key: so.Mapped[bytes] = so.mapped_column(sa.LargeBinary, nullable=False)
    signing_key_id: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    set_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    retired_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuthDeviceSession(db.Model):
    """One interviewer signed in on one device: an access and a refresh token.

    ``previous_refresh_hash`` is the refresh token this row rotated away from
    last and ``retired_refresh_hashes`` the last few (newest first, bounded);
    presenting any of them is reuse and revokes the session with reason
    ``refresh_reuse`` (or ``refresh_retry_race`` inside the lost-response
    grace window after ``refreshed_at``). The ``outstanding_*`` columns are
    the device's last report of unsent interviews for this interviewer
    (policy: outstanding work visible server-side).
    """

    __tablename__ = "auth_device_sessions"
    __table_args__ = (
        sa.Index(
            "ix_auth_device_sessions_retired_refresh_hashes",
            "retired_refresh_hashes",
            postgresql_using="gin",
            postgresql_ops={"retired_refresh_hashes": "jsonb_path_ops"},
        ),
    )

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
    retired_refresh_hashes: so.Mapped[list | None] = so.mapped_column(JSONB, nullable=True)
    refreshed_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_reason: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    outstanding_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    outstanding_unique_ids: so.Mapped[list | None] = so.mapped_column(JSONB, nullable=True)
    outstanding_client_draft_ids: so.Mapped[list | None] = so.mapped_column(JSONB, nullable=True)
    # Registrations made offline and not yet uploaded (the app's client_death_ids).
    outstanding_client_death_ids: so.Mapped[list | None] = so.mapped_column(JSONB, nullable=True)
    outstanding_reported_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class AuthSignInToken(db.Model):
    """A sign-in QR: one single-use token that enrols a device and opens that
    one user's normal device session (docs/policy/mobile-sign-in.md section 8).
    Only the SHA-256 of ``secrets.token_urlsafe(32)`` is stored. At most one is
    pending per user (a newer issue voids the old). Rules:
    app/services/sign_in_qr_service.py."""

    __tablename__ = "auth_sign_in_tokens"
    __table_args__ = (
        sa.Index(
            "ix_auth_sign_in_tokens_pending_user",
            "user_id",
            unique=True,
            postgresql_where=sa.text("redeemed_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: so.Mapped[str] = so.mapped_column(sa.String(64), unique=True, nullable=False)
    issued_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id", ondelete="SET NULL"), nullable=True
    )
    issued_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    redeemed_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    redeemed_device_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_devices.device_id"), nullable=True
    )
    revoked_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    # The user's ``auth_session_version`` at issue: a later bump (sign out
    # everywhere, password or factor reset) makes the token invalid.
    user_session_version: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    # The ``sign_in_qr_expired`` audit row is written once, when first noticed.
    expiry_noted_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
