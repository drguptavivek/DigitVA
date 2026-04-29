import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MapIcd10LegacyReportingAlias(db.Model):
    """Maps historical ICD codes to current ICD-10 2019 reporting codes."""

    __tablename__ = "map_icd10_legacy_reporting_aliases"

    legacy_code: so.Mapped[str] = so.mapped_column(
        sa.String(16),
        primary_key=True,
    )
    reporting_code: so.Mapped[str] = so.mapped_column(
        sa.String(16),
        sa.ForeignKey("mas_icd10_2019_2.code"),
        nullable=False,
        index=True,
    )
    note: so.Mapped[str | None] = so.mapped_column(
        sa.Text(),
        nullable=True,
    )

    reporting_icd: so.Mapped["MasIcd1020192"] = so.relationship()

    def __repr__(self) -> str:
        return f"LegacyReportingAlias({self.legacy_code} -> {self.reporting_code})"
