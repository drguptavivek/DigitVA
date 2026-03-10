import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone


class MapProjectOdk(db.Model):
    """Maps a project to an ODK Central connection.

    A project has at most one connection (unique on project_id).
    Many projects may point to the same connection_id.
    """

    __tablename__ = "map_project_odk"

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    connection_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_odk_connections.connection_id"),
        nullable=False,
        index=True,
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return f"<MapProjectOdk {self.project_id} → {self.connection_id}>"
