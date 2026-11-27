"""Approved applications that call the ICD-11 client API (digitva-ddpf).

Policy: docs/policy/icd11-client-api.md. The token is a 256-bit random value
shown to its holder once; only its SHA-256 digest is stored here. Rules live
in app/services/icd11_client_auth.py.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import ARRAY

from app import db


def _utcnow():
    return datetime.now(UTC)


class AuthIcd11ApiClient(db.Model):
    """One application's ICD-11 API token: scopes, expiry, revocation."""

    __tablename__ = "auth_icd11_api_clients"

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: so.Mapped[str] = so.mapped_column(sa.String(120), nullable=False)
    key_id: so.Mapped[str] = so.mapped_column(sa.String(16), unique=True, nullable=False)
    token_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), unique=True, nullable=False)
    scopes: so.Mapped[list[str]] = so.mapped_column(ARRAY(sa.String(32)), nullable=False)
    expires_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    # The admin list is newest first.
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    revoked_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    last_used_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AuthIcd11ApiClient {self.key_id}>"
