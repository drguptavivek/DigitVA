"""Second-factor credentials and login security events.

Baseline: docs/policy/authentication-factors.md. Additive tables for
passkeys (WebAuthn), TOTP enrolment, recovery codes and a security-event
audit trail, used by the login flow, enrolment enforcement, the admin
"Reset sign-in factors" action and the break-glass CLI
(``flask auth reset-factors``).
"""

import uuid
from datetime import UTC, datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app import db


class AuthWebauthnCredential(db.Model):
    """One registered passkey. A user may hold several."""

    __tablename__ = "auth_webauthn_credentials"

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_id: so.Mapped[bytes] = so.mapped_column(
        sa.LargeBinary, unique=True, nullable=False
    )
    public_key: so.Mapped[bytes] = so.mapped_column(sa.LargeBinary, nullable=False)
    sign_count: so.Mapped[int] = so.mapped_column(
        sa.BigInteger, nullable=False, default=0, server_default="0"
    )
    backup_eligible: so.Mapped[bool | None] = so.mapped_column(sa.Boolean, nullable=True)
    backed_up: so.Mapped[bool | None] = so.mapped_column(sa.Boolean, nullable=True)
    transports: so.Mapped[list[str] | None] = so.mapped_column(ARRAY(sa.String), nullable=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_used_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<AuthWebauthnCredential {self.id} user_id={self.user_id} name={self.name!r}>"


class AuthTotp(db.Model):
    """TOTP enrolment for a user. An unconfirmed row means setup in progress."""

    __tablename__ = "auth_totp"

    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    secret_encrypted: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    last_used_step: so.Mapped[int | None] = so.mapped_column(sa.BigInteger, nullable=True)
    confirmed_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<AuthTotp user_id={self.user_id} confirmed={self.confirmed_at is not None}>"


class AuthRecoveryCode(db.Model):
    """One single-use recovery code, stored only as a keyed hash."""

    __tablename__ = "auth_recovery_codes"

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    used_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<AuthRecoveryCode {self.id} user_id={self.user_id} used={self.used_at is not None}>"


class AuthMobileCode(db.Model):
    """A one-time sign-in code for a mobile-only account, stored only as a
    keyed hash (docs/policy/mobile-sign-in.md section 3). At most one is live
    per user: issuing a new code voids the old; five wrong attempts, or
    redeeming it, end it."""

    __tablename__ = "auth_mobile_codes"
    # At most one live code per person, even under concurrent issuers.
    __table_args__ = (
        sa.Index(
            "ix_auth_mobile_codes_live_user",
            "user_id",
            unique=True,
            postgresql_where=sa.text("redeemed_at IS NULL AND voided_at IS NULL"),
        ),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    issued_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    issued_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    expires_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    failed_attempts: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    redeemed_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    voided_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<AuthMobileCode {self.id} user_id={self.user_id}>"


class AuthSecurityEvent(db.Model):
    """Audit trail for factor changes, resets and counter anomalies.

    Never carries credential IDs in full, public keys, TOTP secrets, codes
    or challenges -- see docs/policy/authentication-factors.md section 9.
    ``detail`` is small and non-secret; the only IP address is the client
    address on ``web_sign_in``.
    """

    __tablename__ = "auth_security_events"
    # Per-account counts in a time window (the device second-factor lockout,
    # app/services/device_auth_service.py).
    __table_args__ = (
        sa.Index("ix_auth_security_events_user_type_time", "user_id", "event_type", "occurred_at"),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False, index=True)
    detail: so.Mapped[dict | None] = so.mapped_column(JSONB, nullable=True)
    occurred_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AuthSecurityEvent {self.event_type} user_id={self.user_id}>"
