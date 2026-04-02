import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaProjectMaster(db.Model):
    __tablename__ = "va_project_master"
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), primary_key=True, index=True
    )
    project_code: so.Mapped[Optional[str]] = so.mapped_column(sa.String(6))
    project_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    project_nickname: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    project_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    project_registered_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    project_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    narrative_qa_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default="false"
    )
    social_autopsy_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=True, server_default="true"
    )
    coding_intake_mode: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        nullable=False,
        default="random_form_allocation",
        server_default="random_form_allocation",
    )
    demo_training_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default="false"
    )
    demo_retention_minutes: so.Mapped[int] = so.mapped_column(
        sa.Integer(),
        nullable=False,
        default=10,
        server_default="10",
    )

    def __repr__(self) -> str:
        return f"VA Project Master -> {self.project_id} ({self.project_status})"
