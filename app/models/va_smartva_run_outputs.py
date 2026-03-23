import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


class VaSmartvaRunOutput(db.Model):
    __tablename__ = "va_smartva_run_outputs"

    va_smartva_run_output_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        default=uuid.uuid4,
        primary_key=True,
        index=True,
    )
    va_smartva_run_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_smartva_runs.va_smartva_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    output_kind: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        nullable=False,
        default="formatted_result_row",
    )
    output_source_name: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(64),
        nullable=True,
    )
    output_row_index: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
    )
    output_sid: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(64),
        nullable=True,
        index=True,
    )
    output_resultfor: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(16),
        nullable=True,
    )
    output_payload: so.Mapped[dict] = so.mapped_column(
        JSONB,
        nullable=False,
    )
    output_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
