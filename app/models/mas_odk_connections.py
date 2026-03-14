import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class MasOdkConnections(db.Model):
    """ODK Central connection master.

    One row per ODK server. Multiple projects may share one connection.
    Username and password are stored encrypted (Fernet + PBKDF2 salt+pepper).
    base_url is stored in plain text — it is not a secret.
    """

    __tablename__ = "mas_odk_connections"

    connection_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    connection_name: so.Mapped[str] = so.mapped_column(
        sa.Text, nullable=False, unique=True
    )
    base_url: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)

    # Encrypted credentials — never return raw values to clients
    username_enc: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    username_salt: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    password_enc: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    password_salt: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)

    status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    notes: so.Mapped[str | None] = so.mapped_column(sa.Text)
    cooldown_until: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    consecutive_failure_count: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0
    )
    last_failure_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_failure_message: so.Mapped[str | None] = so.mapped_column(sa.Text)
    last_success_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_request_started_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<OdkConnection {self.connection_name} ({self.base_url})>"
