import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import date, datetime, timedelta


class VaDailyKpiAggregates(db.Model):
    """Pre-computed daily KPI grid — one row per (snapshot_date, site_id).

    Written by the daily aggregation task (app/tasks/kpi_tasks.py) and read by
    the data-manager KPI endpoints. Mirrors migration d7e8f9a0b1c2; see
    docs/policy/kpis.md for column semantics.
    """

    __tablename__ = "va_daily_kpi_aggregates"
    __table_args__ = (
        sa.PrimaryKeyConstraint("snapshot_date", "site_id", name="pk_va_daily_kpi_aggregates"),
        sa.Index("ix_va_daily_kpi_aggregates_site", "site_id"),
        sa.Index("ix_va_daily_kpi_aggregates_project", "project_id"),
    )

    snapshot_date: so.Mapped[date] = so.mapped_column(sa.Date, nullable=False)
    site_id: so.Mapped[str] = so.mapped_column(
        sa.String(4), sa.ForeignKey("va_site_master.site_id"), nullable=False
    )
    # Owning project on this date (audit)
    project_id: so.Mapped[str] = so.mapped_column(sa.String(6), nullable=False)
    total_submissions: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    new_from_odk: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    updated_from_odk: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    coded_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    pending_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    consent_refused_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    not_codeable_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    coding_duration_min: so.Mapped[timedelta | None] = so.mapped_column(sa.Interval, nullable=True)
    coding_duration_max: so.Mapped[timedelta | None] = so.mapped_column(sa.Interval, nullable=True)
    coding_duration_p50: so.Mapped[timedelta | None] = so.mapped_column(sa.Interval, nullable=True)
    coding_duration_p90: so.Mapped[timedelta | None] = so.mapped_column(sa.Interval, nullable=True)
    reviewer_finalized_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    upstream_changed_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    reopened_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<VaDailyKpiAggregates {self.snapshot_date} {self.site_id}>"
