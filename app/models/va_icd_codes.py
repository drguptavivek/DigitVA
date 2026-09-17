from app import db
import sqlalchemy as sa
import sqlalchemy.orm as so
from typing import Optional


class VaIcdCodes(db.Model):
    """Deprecated as of 2026-04-20. Legacy ICD catalog retained for compatibility."""

    __tablename__ = "va_icd_codes"
    __table_args__ = (
        # Case-insensitive exact lookup and trigram search on the display label.
        sa.Index(
            "ix_va_icd_codes_lower_icd_code",
            sa.text("lower(icd_code::text)"),
        ),
        # The operator class has to ride along in the expression: postgresql_ops
        # cannot key off a text() expression. Alembic therefore cannot diff this
        # index's expression and treats it as equal whenever the name is present.
        sa.Index(
            "ix_va_icd_codes_lower_display_trgm",
            sa.text("lower(icd_to_display) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    disease_id: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer, nullable=True)
    icd_code: so.Mapped[str] = so.mapped_column(sa.String(8), index=True, nullable=False)
    icd_to_display: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    category: so.Mapped[Optional[str]] = so.mapped_column(sa.Text, nullable=True)

    def __repr__(self):
        return f"VA ICD Code: {self.icd_to_display}"
