import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class CodSearchTelemetry(db.Model):
    """Phase-0 COD coding-search telemetry: one row per search request.

    Evidence before build (docs/policy/coding-search-telemetry.md): the query
    term and role are the analytical payload — deliberately no user id, no
    va_sid, no IP. ``chosen_code`` / ``chosen_rank`` / ``chosen_at`` are
    filled later, when the browser forwards the search's id on the conclusive
    COD save. Operational log, deliberately outside the ``mas_*`` / ``map_*``
    / ``auth_*`` conventions (owner decision 2026-09-25); rows are pruned
    after 90 days and leave the system through the admin CSV export.
    """

    __tablename__ = "cod_search_telemetry"
    __table_args__ = (
        # The naming convention (app/__init__.py) already prefixes this with
        # "ck_%(table_name)s_"; pass only the discriminator (digitva-liu).
        sa.CheckConstraint(
            "surface IN ('icd10_coding', 'icd11_coding')",
            name="surface",
        ),
        sa.Index("ix_cod_search_telemetry_created_at", "created_at"),
        sa.Index("ix_cod_search_telemetry_search_id", "search_id"),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )
    search_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        nullable=False,
    )
    surface: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    query_text: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    result_count: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    zero_results: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    vocabulary_hit: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    latency_ms: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    role: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    chosen_code: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    chosen_rank: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    chosen_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=sa.text("now()"),
    )

    def __repr__(self) -> str:
        return f"<CodSearchTelemetry {self.surface}:{self.query_text!r}:{self.result_count}>"
