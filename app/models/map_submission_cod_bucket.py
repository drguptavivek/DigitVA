import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MapSubmissionCodBucket(db.Model):
    """One death's COD bucket in one active scheme, per matching age band.

    Precomputed from the analytics MVs by
    ``app/services/cod_bucket_materialization.py`` with the same SQL the live
    report runs (``_cod_bucket_resolved_rows``), so a report over these rows
    equals the live derivation. A band gap gives a death no row, an overlap
    gives it two. ``node_id`` NULL: the final COD matches no active mapping.
    Every column a report filters or groups on is here, so the reports need
    no join back to submissions or the MVs. No names, free text or PII.
    Policy: docs/policy/cod-bucket-reporting.md ("Precomputed reporting rows").
    """

    __tablename__ = "map_submission_cod_bucket"
    __table_args__ = (
        # The read paths: a scheme, the reportable rows, then the scope
        # filters in the order the reports narrow them.
        sa.Index(
            "ix_map_submission_cod_bucket_report",
            "scheme_id",
            "project_id",
            "site_id",
            "form_id",
            postgresql_include=[
                "age_band_id",
                "node_id",
                "gender",
                "submission_date",
                "event_date",
                "age_days",
                "org_unit_id",
            ],
            postgresql_where=sa.text("is_reportable"),
        ),
        # A unit grant's scope: its subtree's unit ids.
        sa.Index(
            "ix_map_submission_cod_bucket_unit",
            "scheme_id",
            "org_unit_id",
            postgresql_where=sa.text("is_reportable"),
        ),
        # The diff-sync's per-scheme delete and the age band FK cascade.
        sa.Index("ix_map_submission_cod_bucket_scheme_band", "scheme_id", "age_band_id"),
        # The node FK's ON DELETE SET NULL.
        sa.Index("ix_map_submission_cod_bucket_node", "node_id"),
        sa.CheckConstraint(
            "icd_classification IN ('icd10', 'icd11')",
            name="icd_classification",
        ),
    )

    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE", name="fk_map_submission_cod_bucket_va_sid"),
        primary_key=True,
    )
    scheme_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_schemes.scheme_id", ondelete="CASCADE", name="fk_map_submission_cod_bucket_scheme"),
        primary_key=True,
    )
    age_band_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_scheme_age_bands.age_band_id", ondelete="CASCADE", name="fk_map_submission_cod_bucket_age_band"),
        primary_key=True,
    )
    # The band's age_scope, denormalised; NULL is all ages.
    age_scope: so.Mapped[str | None] = so.mapped_column(sa.String(32))
    icd_classification: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    # The ICD-10 code or the ICD-11 stem of the final COD.
    final_icd: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    # ICD-10: the legacy alias, else the code. ICD-11: the nearest mapped
    # ancestor, else the stem.
    reporting_icd: so.Mapped[str | None] = so.mapped_column(sa.Text)
    node_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_nodes.node_id", ondelete="SET NULL", name="fk_map_submission_cod_bucket_node"),
    )
    project_id: so.Mapped[str | None] = so.mapped_column(sa.String(6))
    site_id: so.Mapped[str | None] = so.mapped_column(sa.String(4))
    form_id: so.Mapped[str] = so.mapped_column(sa.String(12), nullable=False)
    org_unit_id: so.Mapped[uuid.UUID | None] = so.mapped_column(sa.Uuid(as_uuid=True))
    # As recorded: the reports normalise it two ways (with and without trim).
    gender: so.Mapped[str | None] = so.mapped_column(sa.String(20))
    age_days: so.Mapped[Decimal] = so.mapped_column(sa.Numeric, nullable=False)
    age_years: so.Mapped[Decimal | None] = so.mapped_column(sa.Numeric)
    submission_date: so.Mapped[date | None] = so.mapped_column(sa.Date)
    # The earliest non-duplicate, non-cancelled case date of death, else the
    # submission date: the area summary's ``death_date_from``.
    event_date: so.Mapped[date | None] = so.mapped_column(sa.Date)
    # Not retired from ODK and not a confirmed duplicate.
    is_reportable: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False)
    computed_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<MapSubmissionCodBucket {self.va_sid} {self.scheme_id} {self.age_band_id}>"
