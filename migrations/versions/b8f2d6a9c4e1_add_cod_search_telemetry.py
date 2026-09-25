"""add cod_search_telemetry, the phase-0 coding-search log

Revision ID: b8f2d6a9c4e1
Revises: e9d4b6f8a3c2
Create Date: 2026-09-25 12:00:00.000000

digitva-zpe.3. Policy: docs/policy/coding-search-telemetry.md.

One row per COD coding-search request (query text, result count, latency,
role) plus the eventually chosen code when the browser forwards the search
id on the conclusive COD save. Operational log, deliberately outside the
``mas_*`` / ``map_*`` / ``auth_*`` conventions (owner decision 2026-09-25).
Schema only — rows are written by the app and pruned after 90 days; nothing
is seeded. Downgrade drops the log with it: export
/admin/api/coding-search-telemetry/export.csv first if the evidence matters.
"""

import sqlalchemy as sa
from alembic import op

revision = "b8f2d6a9c4e1"
down_revision = "e9d4b6f8a3c2"
branch_labels = None
depends_on = None

TABLE = "cod_search_telemetry"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("search_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("query_text", sa.String(length=128), nullable=False),
        sa.Column("result_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("zero_results", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("vocabulary_hit", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("chosen_code", sa.String(length=16), nullable=True),
        sa.Column("chosen_rank", sa.Integer(), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cod_search_telemetry")),
        sa.CheckConstraint(
            "surface IN ('icd10_coding', 'icd11_coding')",
            name="surface",
        ),
    )
    op.create_index("ix_cod_search_telemetry_created_at", TABLE, ["created_at"], unique=False)
    op.create_index("ix_cod_search_telemetry_search_id", TABLE, ["search_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cod_search_telemetry_search_id", table_name=TABLE)
    op.drop_index("ix_cod_search_telemetry_created_at", table_name=TABLE)
    op.drop_table(TABLE)
