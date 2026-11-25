"""Explicit WHO VA cause code on COD bucket nodes.

Revision ID: b5e2c8d4a9f7
Revises: c3a7e1f9d4b2
Create Date: 2026-11-25

digitva-0o3z, owner decision 2026-11-25: an admin can give a disease bucket
its WHO VA cause code (``VAs-01.09``) in the COD bucket editor. The code is
stored in a new nullable ``mas_cod_bucket_nodes.va_code``; NULL keeps the code
derived from ``node_code`` (``vas_01_09`` -> ``VAs-01.09``), so behaviour is
unchanged until an admin sets one. ``node_code`` is never renamed. Policy:
docs/policy/cod-bucket-reporting.md ("VA cause code of a bucket").

Chained onto c3a7e1f9d4b2. Additive, no backfill. Downgrade drops the
column, losing any codes set since (a scheme JSON export or snapshot keeps
them).
"""

import sqlalchemy as sa
from alembic import op

revision = "b5e2c8d4a9f7"
down_revision = "c3a7e1f9d4b2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mas_cod_bucket_nodes",
        sa.Column("va_code", sa.String(length=16), nullable=True),
    )


def downgrade():
    op.drop_column("mas_cod_bucket_nodes", "va_code")
