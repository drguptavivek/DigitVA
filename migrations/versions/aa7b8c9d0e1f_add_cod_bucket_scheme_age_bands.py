"""add cod bucket scheme age bands

Revision ID: aa7b8c9d0e1f
Revises: a6b7c8d9e0f1
Create Date: 2026-04-20T00:30:00.000000

"""

import uuid

from alembic import op
import sqlalchemy as sa


revision = "aa7b8c9d0e1f"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


SCHEME_CODE_SRS_INDIA = "SRS_INDIA"
SCHEME_CODE_CMEA10 = "CMEA10"


def _age_scope_label(age_scope):
    if age_scope == "adult_over5y":
        return "Adult / Over 5 Years"
    if age_scope == "child_1_59m":
        return "Child / 1-59 Months"
    if age_scope == "neonate":
        return "Neonate"
    return age_scope or "All Ages"


def _default_band_metadata(scheme_code, age_scope):
    if scheme_code == SCHEME_CODE_SRS_INDIA and age_scope == "adult_over5y":
        return {
            "age_label": "Adult / Over 5 Years",
            "min_age_value": 5,
            "min_age_unit": "years",
            "max_age_value": None,
            "max_age_unit": None,
            "level_count": 3,
        }
    if scheme_code == SCHEME_CODE_SRS_INDIA and age_scope == "child_1_59m":
        return {
            "age_label": "Child / 1-59 Months",
            "min_age_value": 1,
            "min_age_unit": "months",
            "max_age_value": 60,
            "max_age_unit": "months",
            "level_count": 3,
        }
    if scheme_code == SCHEME_CODE_SRS_INDIA and age_scope == "neonate":
        return {
            "age_label": "Neonate",
            "min_age_value": 0,
            "min_age_unit": "days",
            "max_age_value": 29,
            "max_age_unit": "days",
            "level_count": 3,
        }
    if scheme_code == SCHEME_CODE_CMEA10:
        return {
            "age_label": "All Ages",
            "min_age_value": None,
            "min_age_unit": None,
            "max_age_value": None,
            "max_age_unit": None,
            "level_count": 1,
        }
    return {
        "age_label": _age_scope_label(age_scope),
        "min_age_value": None,
        "min_age_unit": None,
        "max_age_value": None,
        "max_age_unit": None,
        "level_count": None,
    }


def _compute_level_count(bind, nodes_table, scheme_id, age_scope):
    query = sa.select(
        nodes_table.c.node_id,
        nodes_table.c.parent_node_id,
    ).where(nodes_table.c.scheme_id == scheme_id)
    if age_scope is None:
        query = query.where(nodes_table.c.age_scope.is_(None))
    else:
        query = query.where(nodes_table.c.age_scope == age_scope)

    rows = bind.execute(query).all()
    if not rows:
        return 1

    parent_by_id = {row.node_id: row.parent_node_id for row in rows}
    max_depth = 1
    for node_id in parent_by_id:
        depth = 1
        parent_id = parent_by_id[node_id]
        while parent_id is not None:
            depth += 1
            parent_id = parent_by_id.get(parent_id)
        max_depth = max(max_depth, depth)
    return max_depth


def upgrade():
    op.create_table(
        "mas_cod_bucket_scheme_age_bands",
        sa.Column("age_band_id", sa.Uuid(), nullable=False),
        sa.Column("scheme_id", sa.Uuid(), nullable=False),
        sa.Column("age_scope", sa.String(length=32), nullable=True),
        sa.Column("age_label", sa.String(length=128), nullable=False),
        sa.Column("min_age_value", sa.Integer(), nullable=True),
        sa.Column("min_age_unit", sa.String(length=8), nullable=True),
        sa.Column("max_age_value", sa.Integer(), nullable=True),
        sa.Column("max_age_unit", sa.String(length=8), nullable=True),
        sa.Column("level_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["scheme_id"],
            ["mas_cod_bucket_schemes.scheme_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("age_band_id"),
    )
    op.create_index(
        "ix_mas_cod_bucket_scheme_age_bands_scheme",
        "mas_cod_bucket_scheme_age_bands",
        ["scheme_id"],
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    schemes_table = sa.Table(
        "mas_cod_bucket_schemes",
        metadata,
        sa.Column("scheme_id", sa.Uuid()),
        sa.Column("scheme_code", sa.String(length=32)),
    )
    nodes_table = sa.Table(
        "mas_cod_bucket_nodes",
        metadata,
        sa.Column("node_id", sa.Uuid()),
        sa.Column("scheme_id", sa.Uuid()),
        sa.Column("age_scope", sa.String(length=32)),
        sa.Column("parent_node_id", sa.Uuid()),
    )
    age_bands_table = sa.Table(
        "mas_cod_bucket_scheme_age_bands",
        metadata,
        sa.Column("age_band_id", sa.Uuid()),
        sa.Column("scheme_id", sa.Uuid()),
        sa.Column("age_scope", sa.String(length=32)),
        sa.Column("age_label", sa.String(length=128)),
        sa.Column("min_age_value", sa.Integer()),
        sa.Column("min_age_unit", sa.String(length=8)),
        sa.Column("max_age_value", sa.Integer()),
        sa.Column("max_age_unit", sa.String(length=8)),
        sa.Column("level_count", sa.Integer()),
        sa.Column("sort_order", sa.Integer()),
        sa.Column("is_active", sa.Boolean()),
    )

    scheme_rows = bind.execute(sa.select(
        schemes_table.c.scheme_id,
        schemes_table.c.scheme_code,
    )).all()
    for scheme_id, scheme_code in scheme_rows:
        age_scope_rows = bind.execute(
            sa.select(nodes_table.c.age_scope)
            .where(nodes_table.c.scheme_id == scheme_id)
            .distinct()
            .order_by(nodes_table.c.age_scope.asc().nullsfirst())
        ).scalars().all()

        if not age_scope_rows:
            age_scope_rows = [None]

        for index, age_scope in enumerate(age_scope_rows, start=1):
            meta = _default_band_metadata(scheme_code, age_scope)
            level_count = meta["level_count"] or _compute_level_count(
                bind,
                nodes_table,
                scheme_id,
                age_scope,
            )
            bind.execute(
                age_bands_table.insert().values(
                    age_band_id=uuid.uuid4(),
                    scheme_id=scheme_id,
                    age_scope=age_scope,
                    age_label=meta["age_label"],
                    min_age_value=meta["min_age_value"],
                    min_age_unit=meta["min_age_unit"],
                    max_age_value=meta["max_age_value"],
                    max_age_unit=meta["max_age_unit"],
                    level_count=level_count,
                    sort_order=index,
                    is_active=True,
                )
            )


def downgrade():
    op.drop_index(
        "ix_mas_cod_bucket_scheme_age_bands_scheme",
        table_name="mas_cod_bucket_scheme_age_bands",
    )
    op.drop_table("mas_cod_bucket_scheme_age_bands")
