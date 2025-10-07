from app import db
import sqlalchemy as sa
import sqlalchemy.orm as so
from typing import Optional


class VaIcdCodes(db.Model):
    __tablename__ = "va_icd_codes"

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    disease_id: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer, nullable=True)
    icd_code: so.Mapped[str] = so.mapped_column(sa.String(8), index=True, nullable=False)
    icd_to_display: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    category: so.Mapped[Optional[str]] = so.mapped_column(sa.Text, nullable=True)

    def __repr__(self):
        return f"VA ICD Code: {self.icd_to_display}"