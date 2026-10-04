"""Record every composed form version the server has served.

Beads digitva-xuf9 / digitva-6pwq. ``mas_instrument_versions`` holds one row per
(instrument, composed version): ``activated_at`` is when the server first
served it and ``definition`` the complete composed definition, kept so an upload
filled on an older version can be re-checked against that version's rules.
Additive and reversible; the table starts empty and fills as versions are
served.

Revision ID: a8c4e2f6b9d1
Revises: f7b3d9e1a5c4
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a8c4e2f6b9d1"
down_revision = "f7b3d9e1a5c4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mas_instrument_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_code", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("instrument_code", "version", name="uq_mas_instrument_versions_code_version"),
    )


def downgrade():
    op.drop_table("mas_instrument_versions")
