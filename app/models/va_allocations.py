import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaAllocation, VaStatuses


class VaAllocations(db.Model):
    __tablename__ = "va_allocations"

    va_allocation_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), index=True, nullable=False
    )
    va_allocated_to: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), index=True, nullable=False
    )
    va_allocation_for: so.Mapped[VaAllocation] = so.mapped_column(
        sa.Enum(VaAllocation, name="allocation_enum"),
        nullable=False,
        index=True
    )
    va_allocation_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True
    )
    va_allocation_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_allocation_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # Serves "user's most recent allocation of a kind" (last_allocated_project_id).
        sa.Index(
            "ix_va_allocations_to_for_createdat",
            "va_allocated_to",
            "va_allocation_for",
            "va_allocation_createdat",
        ),
    )

    def __repr__(self):
        return f"VA Allocation -> {self.va_sid} ({self.va_allocation_status}): for {self.va_allocation_for} to {self.va_allocated_to}"