"""Add mas_ui_string_override.source (digitva-cqw9).

Revision ID: q7c2n5x9d4b8
Revises: f3c8a1d5b7e2
Create Date: 2026-10-24 09:00:00.000000

``machine`` rows are Azure Translator candidates awaiting review; they are never
served. ``edited`` rows are what the table held before and what a human saves or
accepts. Additive: existing rows become ``edited`` through the server default.
Downgrade refuses while machine rows exist (they are not corrections and would
be mistaken for them once the column is gone).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "q7c2n5x9d4b8"
down_revision = "f3c8a1d5b7e2"
branch_labels = None
depends_on = None

TABLE = "mas_ui_string_override"
CHECK = "ck_mas_ui_string_override_source"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column("source", sa.String(length=16), nullable=False, server_default="edited"),
    )
    op.create_check_constraint(CHECK, TABLE, "source IN ('machine', 'edited')")


def downgrade():
    remaining = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE source = 'machine'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} machine UI string candidate(s) exist; reject or accept them "
            "in the admin page before downgrading."
        )
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "source")
