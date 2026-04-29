import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MasCodBucketScheme(db.Model):
    """Versioned reporting taxonomy for cause-of-death bucket aggregation."""

    __tablename__ = "mas_cod_bucket_schemes"

    scheme_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scheme_code: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, unique=True, index=True
    )
    scheme_name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    scheme_description: so.Mapped[str | None] = so.mapped_column(sa.Text)
    source_path: so.Mapped[str | None] = so.mapped_column(sa.String(512))
    mapping_version: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False, default=1)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    nodes: so.Mapped[list["MasCodBucketNode"]] = so.relationship(
        "MasCodBucketNode",
        back_populates="scheme",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    age_bands: so.Mapped[list["MasCodBucketSchemeAgeBand"]] = so.relationship(
        "MasCodBucketSchemeAgeBand",
        back_populates="scheme",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MasCodBucketSchemeAgeBand.sort_order",
    )
    mappings: so.Mapped[list["MapIcdCodBucket"]] = so.relationship(
        "MapIcdCodBucket",
        back_populates="scheme",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<MasCodBucketScheme {self.scheme_code}>"


class MasCodBucketSchemeAgeBand(db.Model):
    """Age-band metadata for a reporting scheme."""

    __tablename__ = "mas_cod_bucket_scheme_age_bands"
    __table_args__ = (
        sa.Index("ix_mas_cod_bucket_scheme_age_bands_scheme", "scheme_id"),
    )

    age_band_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scheme_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_schemes.scheme_id", ondelete="CASCADE"),
        nullable=False,
    )
    age_scope: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    age_label: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    min_age_value: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    min_age_unit: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    max_age_value: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    max_age_unit: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    level_count: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False, default=3)
    sort_order: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False, default=0)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    scheme: so.Mapped["MasCodBucketScheme"] = so.relationship(
        "MasCodBucketScheme",
        back_populates="age_bands",
    )

    def __repr__(self) -> str:
        return f"<MasCodBucketSchemeAgeBand {self.age_scope or 'all'}>"


class MasCodBucketNode(db.Model):
    """Hierarchy node within a cause-of-death reporting scheme."""

    __tablename__ = "mas_cod_bucket_nodes"
    __table_args__ = (
        sa.UniqueConstraint(
            "scheme_id",
            "age_scope",
            "node_type",
            "parent_node_id",
            "node_code",
            name="uq_mas_cod_bucket_nodes_scheme_scope_type_parent_code",
        ),
        sa.Index("ix_mas_cod_bucket_nodes_scheme", "scheme_id"),
        sa.Index("ix_mas_cod_bucket_nodes_parent", "parent_node_id"),
    )

    node_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scheme_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_schemes.scheme_id", ondelete="CASCADE"),
        nullable=False,
    )
    age_scope: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    node_type: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    parent_node_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_nodes.node_id", ondelete="CASCADE"),
        nullable=True,
    )
    node_code: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    node_label: so.Mapped[str] = so.mapped_column(sa.String(256), nullable=False)
    sort_order: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False, default=0)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    scheme: so.Mapped["MasCodBucketScheme"] = so.relationship(
        "MasCodBucketScheme",
        back_populates="nodes",
    )
    parent: so.Mapped["MasCodBucketNode | None"] = so.relationship(
        "MasCodBucketNode",
        remote_side=[node_id],
        back_populates="children",
    )
    children: so.Mapped[list["MasCodBucketNode"]] = so.relationship(
        "MasCodBucketNode",
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    icd_mappings: so.Mapped[list["MapIcdCodBucket"]] = so.relationship(
        "MapIcdCodBucket",
        back_populates="node",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<MasCodBucketNode {self.node_type}:{self.node_code}>"


class MapIcdCodBucket(db.Model):
    """ICD-to-bucket leaf-node mapping for a reporting scheme."""

    __tablename__ = "map_icd_cod_buckets"
    __table_args__ = (
        sa.UniqueConstraint(
            "scheme_id",
            "age_scope",
            "icd_code",
            name="uq_map_icd_cod_buckets_scheme_scope_icd",
        ),
        sa.Index(
            "ux_map_icd_cod_buckets_scheme_scope_icd_norm",
            "scheme_id",
            sa.text("COALESCE(age_scope, '')"),
            sa.text("upper(icd_code)"),
            unique=True,
        ),
        sa.Index("ix_map_icd_cod_buckets_scheme", "scheme_id"),
        sa.Index("ix_map_icd_cod_buckets_node", "node_id"),
        sa.Index("ix_map_icd_cod_buckets_icd_code", "icd_code"),
    )

    mapping_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scheme_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_schemes.scheme_id", ondelete="CASCADE"),
        nullable=False,
    )
    age_scope: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    icd_code: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    node_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_nodes.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_sheet: so.Mapped[str | None] = so.mapped_column(sa.String(128))
    source_row_number: so.Mapped[int | None] = so.mapped_column(sa.Integer)
    source_category: so.Mapped[str | None] = so.mapped_column(sa.String(256))
    match_type: so.Mapped[str | None] = so.mapped_column(sa.String(32))
    mapping_note: so.Mapped[str | None] = so.mapped_column(sa.Text)
    is_active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    scheme: so.Mapped["MasCodBucketScheme"] = so.relationship(
        "MasCodBucketScheme",
        back_populates="mappings",
    )
    node: so.Mapped["MasCodBucketNode"] = so.relationship(
        "MasCodBucketNode",
        back_populates="icd_mappings",
    )

    def __repr__(self) -> str:
        return f"<MapIcdCodBucket {self.icd_code} -> {self.node_id}>"
