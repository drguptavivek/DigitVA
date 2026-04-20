"""add cod bucket scheme tables

Revision ID: a6b7c8d9e0f1
Revises: e1f2a3b4c5d7
Create Date: 2026-04-20T00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f1"
down_revision = "e1f2a3b4c5d7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mas_cod_bucket_schemes",
        sa.Column("scheme_id", sa.Uuid(), nullable=False),
        sa.Column("scheme_code", sa.String(length=32), nullable=False),
        sa.Column("scheme_name", sa.String(length=128), nullable=False),
        sa.Column("scheme_description", sa.Text(), nullable=True),
        sa.Column("source_path", sa.String(length=512), nullable=True),
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("scheme_id"),
    )
    op.create_index(
        "ix_mas_cod_bucket_schemes_scheme_code",
        "mas_cod_bucket_schemes",
        ["scheme_code"],
        unique=True,
    )

    op.create_table(
        "mas_cod_bucket_nodes",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("scheme_id", sa.Uuid(), nullable=False),
        sa.Column("age_scope", sa.String(length=32), nullable=True),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("parent_node_id", sa.Uuid(), nullable=True),
        sa.Column("node_code", sa.String(length=128), nullable=False),
        sa.Column("node_label", sa.String(length=256), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["parent_node_id"],
            ["mas_cod_bucket_nodes.node_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scheme_id"],
            ["mas_cod_bucket_schemes.scheme_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("node_id"),
        sa.UniqueConstraint(
            "scheme_id",
            "age_scope",
            "node_type",
            "parent_node_id",
            "node_code",
            name="uq_mas_cod_bucket_nodes_scheme_scope_type_parent_code",
        ),
    )
    op.create_index("ix_mas_cod_bucket_nodes_scheme", "mas_cod_bucket_nodes", ["scheme_id"])
    op.create_index("ix_mas_cod_bucket_nodes_parent", "mas_cod_bucket_nodes", ["parent_node_id"])

    op.create_table(
        "map_icd_cod_buckets",
        sa.Column("mapping_id", sa.Uuid(), nullable=False),
        sa.Column("scheme_id", sa.Uuid(), nullable=False),
        sa.Column("age_scope", sa.String(length=32), nullable=True),
        sa.Column("icd_code", sa.String(length=16), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("source_sheet", sa.String(length=128), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("source_category", sa.String(length=256), nullable=True),
        sa.Column("match_type", sa.String(length=32), nullable=True),
        sa.Column("mapping_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["mas_cod_bucket_nodes.node_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scheme_id"],
            ["mas_cod_bucket_schemes.scheme_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("mapping_id"),
        sa.UniqueConstraint(
            "scheme_id",
            "age_scope",
            "icd_code",
            name="uq_map_icd_cod_buckets_scheme_scope_icd",
        ),
    )
    op.create_index("ix_map_icd_cod_buckets_scheme", "map_icd_cod_buckets", ["scheme_id"])
    op.create_index("ix_map_icd_cod_buckets_node", "map_icd_cod_buckets", ["node_id"])
    op.create_index("ix_map_icd_cod_buckets_icd_code", "map_icd_cod_buckets", ["icd_code"])


def downgrade():
    op.drop_index("ix_map_icd_cod_buckets_icd_code", table_name="map_icd_cod_buckets")
    op.drop_index("ix_map_icd_cod_buckets_node", table_name="map_icd_cod_buckets")
    op.drop_index("ix_map_icd_cod_buckets_scheme", table_name="map_icd_cod_buckets")
    op.drop_table("map_icd_cod_buckets")

    op.drop_index("ix_mas_cod_bucket_nodes_parent", table_name="mas_cod_bucket_nodes")
    op.drop_index("ix_mas_cod_bucket_nodes_scheme", table_name="mas_cod_bucket_nodes")
    op.drop_table("mas_cod_bucket_nodes")

    op.drop_index("ix_mas_cod_bucket_schemes_scheme_code", table_name="mas_cod_bucket_schemes")
    op.drop_table("mas_cod_bucket_schemes")
