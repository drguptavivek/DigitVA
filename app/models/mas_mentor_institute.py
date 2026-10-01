"""Mentoring institutes: cross-project master plus district and staff maps.

A mentoring institute (e.g. a medical college) supports districts from outside
the service tree. It is not an org unit. The maps are only a *guard* on writing
grants (``app/services/mentor_institute_service.py``); access itself comes from
ordinary unit grants. Policy: docs/policy/organization-model.md,
"Mentoring institutes".
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MasMentorInstitute(db.Model):
    __tablename__ = "mas_mentor_institute"

    institute_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    institute_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False, unique=True)
    institute_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<MasMentorInstitute {self.institute_code}>"


class MapMentorInstituteOrgUnit(db.Model):
    """Institute supports a district-level unit (many to many)."""

    __tablename__ = "map_mentor_institute_org_unit"
    __table_args__ = (sa.Index("ix_map_mentor_institute_org_unit_unit", "org_unit_id"),)

    institute_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_mentor_institute.institute_id", ondelete="CASCADE"),
        primary_key=True,
    )
    org_unit_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_unit.org_unit_id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )


class MapMentorInstituteUser(db.Model):
    """User is staff of an institute (many to many)."""

    __tablename__ = "map_mentor_institute_user"
    __table_args__ = (sa.Index("ix_map_mentor_institute_user_user", "user_id"),)

    institute_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_mentor_institute.institute_id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
