import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB, ARRAY


class VaSubmissions(db.Model):
    __tablename__ = "va_submissions"
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), primary_key=True, index=True
    )
    va_form_id: so.Mapped[str] = so.mapped_column(
        sa.String(12), sa.ForeignKey("va_forms.form_id"), index=True
    )
    va_submission_date: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True, index=True
    )
    va_odk_updatedat: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True, index=True
    )
    va_data_collector: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    va_odk_reviewstate: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(16), nullable=True, index=True
    )
    va_instance_name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=True)
    va_uniqueid_real: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128), nullable=True)
    va_uniqueid_masked: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128), nullable=False)    
    va_consent: so.Mapped[str] = so.mapped_column(
        sa.String(4), nullable=False, index=True
    )
    va_narration_language: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, index=True
    )
    va_deceased_age: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    va_deceased_gender: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    va_data: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    va_summary: so.Mapped[Optional[list[str]]] = so.mapped_column(
        ARRAY(sa.String), nullable=True
    )
    va_catcount: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    va_category_list: so.Mapped[list[str]] = so.mapped_column(
        ARRAY(sa.String), nullable=False
    )
    va_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"VA Submission -> {self.va_sid}"