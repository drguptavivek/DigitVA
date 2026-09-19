"""Health-system organization model: per-project levels, units, cadres, workers.

Plan: docs/planning/health-system-organization-model-plan.md
Policy: docs/policy/organization-model.md

Unit codes and cadre codes are unique within a project only. The unit tree
is kept as an ltree ``path`` of unit codes so subtree queries are one index
lookup (``path <@ 'DIST01.CHC01'``).
"""
import uuid
from datetime import UTC, date as date_type, datetime
from decimal import Decimal

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.types import UserDefinedType

from app import db


class LTREE(UserDefinedType):
    """PostgreSQL ltree column (extension enabled by the migration)."""

    cache_ok = True

    def get_col_spec(self, **kw):
        return "LTREE"

    def bind_processor(self, dialect):
        return None

    def result_processor(self, dialect, coltype):
        return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


ABOVE_SCOPE_CODING_MODES = ("code_any", "view_only")


class MasOrgLevel(db.Model):
    """One level of a project's organization tree (District, CHC, PHC, ...)."""

    __tablename__ = "mas_org_level"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "level_code", name="uq_mas_org_level_project_code"),
        sa.UniqueConstraint("project_id", "depth", name="uq_mas_org_level_project_depth"),
        sa.CheckConstraint("depth >= 1", name="ck_mas_org_level_depth_positive"),
    )

    org_level_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id"),
        nullable=False,
        index=True,
    )
    level_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    level_name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    depth: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    is_optional: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    units: so.Mapped[list["MasOrgUnit"]] = so.relationship(
        "MasOrgUnit", back_populates="level", lazy="dynamic"
    )
    level_cadres: so.Mapped[list["MapOrgLevelCadre"]] = so.relationship(
        "MapOrgLevelCadre", back_populates="level", lazy="dynamic"
    )

    @property
    def odk_field_name(self) -> str:
        """Standardized ODK form field carrying this level's unit code."""
        return f"org_{self.level_code}_code"

    def __repr__(self) -> str:
        return f"<MasOrgLevel {self.project_id}/{self.level_code} depth={self.depth}>"


class MasOrgUnit(db.Model):
    """A node of a project's organization tree with contact and location data."""

    __tablename__ = "mas_org_unit"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "unit_code", name="uq_mas_org_unit_project_code"),
        sa.Index("ix_mas_org_unit_path", "path", postgresql_using="gist"),
        sa.Index("ix_mas_org_unit_parent", "parent_org_unit_id"),
    )

    org_unit_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id"),
        nullable=False,
        index=True,
    )
    org_level_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_level.org_level_id"),
        nullable=False,
        index=True,
    )
    parent_org_unit_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_unit.org_unit_id"),
        nullable=True,
    )
    unit_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    unit_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    # ltree of unit codes from the top of the tree down to this unit.
    path: so.Mapped[str] = so.mapped_column(LTREE(), nullable=False)
    address: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    phone: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    latitude: so.Mapped[Decimal | None] = so.mapped_column(sa.Numeric(9, 6), nullable=True)
    longitude: so.Mapped[Decimal | None] = so.mapped_column(sa.Numeric(9, 6), nullable=True)
    google_maps_url: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    remarks: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    level: so.Mapped["MasOrgLevel"] = so.relationship("MasOrgLevel", back_populates="units")
    parent: so.Mapped["MasOrgUnit | None"] = so.relationship(
        "MasOrgUnit", remote_side=[org_unit_id], foreign_keys=[parent_org_unit_id]
    )
    workers: so.Mapped[list["MasOrgUnitWorker"]] = so.relationship(
        "MasOrgUnitWorker", back_populates="unit", lazy="dynamic"
    )

    def __repr__(self) -> str:
        return f"<MasOrgUnit {self.project_id}/{self.unit_code}>"


class MapOrgUnitCodingGate(db.Model):
    """Per-unit coding gate that narrows the site coding gate for one subtree.

    One row per gated unit (``org_unit_id`` unique via the primary key). A
    unit with **no row is not gated** — absence is not a closed unit. Where a
    row exists, it applies to this unit and to every descendant that does not
    set its own row (nearest gated ancestor wins — resolved with a single
    ltree containment query, see
    ``app.services.org_grant_service.resolve_unit_coding_gates``).

    A unit gate can only narrow what ``VaProjectSites`` already allows for
    the submission's site, never widen it: both gates are evaluated and the
    stricter of the two applies. ``daily_coder_limit`` is nullable here
    (unlike the site column) because a unit gate may exist purely to close a
    date window or disable coding, with no unit-specific cap.

    See docs/policy/organization-model.md ("Coding scope") and
    .tasks/org-per-unit-coding-gates.md for the full design.
    """

    __tablename__ = "map_org_unit_coding_gate"

    org_unit_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_unit.org_unit_id"),
        primary_key=True,
    )
    coding_enabled: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    coding_start_date: so.Mapped[date_type | None] = so.mapped_column(sa.Date, nullable=True)
    coding_end_date: so.Mapped[date_type | None] = so.mapped_column(sa.Date, nullable=True)
    daily_coder_limit: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    unit: so.Mapped["MasOrgUnit"] = so.relationship("MasOrgUnit")

    def __repr__(self) -> str:
        return f"<MapOrgUnitCodingGate unit={self.org_unit_id} enabled={self.coding_enabled}>"


class MasCadre(db.Model):
    """A workforce cadre within a project (SMO, MO, CHO, MPW, ANM, ASHA, ...)."""

    __tablename__ = "mas_cadre"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "cadre_code", name="uq_mas_cadre_project_code"),
    )

    cadre_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id"),
        nullable=False,
        index=True,
    )
    cadre_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    cadre_name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    level_cadres: so.Mapped[list["MapOrgLevelCadre"]] = so.relationship(
        "MapOrgLevelCadre", back_populates="cadre", lazy="dynamic"
    )

    def __repr__(self) -> str:
        return f"<MasCadre {self.project_id}/{self.cadre_code}>"


class MapOrgLevelCadre(db.Model):
    """Which cadres exist at a level and whether they may fill or code VA forms."""

    __tablename__ = "map_org_level_cadre"
    __table_args__ = (
        sa.UniqueConstraint("org_level_id", "cadre_id", name="uq_map_org_level_cadre"),
    )

    level_cadre_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_level_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_level.org_level_id"),
        nullable=False,
        index=True,
    )
    cadre_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cadre.cadre_id"),
        nullable=False,
        index=True,
    )
    can_fill_va_form: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    can_code_va_form: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    level: so.Mapped["MasOrgLevel"] = so.relationship("MasOrgLevel", back_populates="level_cadres")
    cadre: so.Mapped["MasCadre"] = so.relationship("MasCadre", back_populates="level_cadres")

    def __repr__(self) -> str:
        return f"<MapOrgLevelCadre level={self.org_level_id} cadre={self.cadre_id}>"


class MasOrgUnitWorker(db.Model):
    """A health worker attached to a unit; may or may not have a DigitVA login.

    Worker name and phone are personal data: exports are admin-only.
    """

    __tablename__ = "mas_org_unit_worker"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "worker_code", name="uq_mas_org_unit_worker_project_code"),
        sa.Index("ix_mas_org_unit_worker_unit", "org_unit_id"),
    )

    worker_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id"),
        nullable=False,
        index=True,
    )
    org_unit_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_unit.org_unit_id"),
        nullable=False,
    )
    cadre_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cadre.cadre_id"),
        nullable=False,
        index=True,
    )
    worker_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    worker_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    phone: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        nullable=True,
        index=True,
    )
    remarks: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    unit: so.Mapped["MasOrgUnit"] = so.relationship("MasOrgUnit", back_populates="workers")
    cadre: so.Mapped["MasCadre"] = so.relationship("MasCadre")

    def __repr__(self) -> str:
        return f"<MasOrgUnitWorker {self.project_id}/{self.worker_code}>"
