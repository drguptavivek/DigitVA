"""Add va_users.public_demo_keep: an admin-kept public-demo account.

Revision ID: d8e2a6c4f1b7
Revises: f3d9b5c7a2e4
Create Date: 2026-10-27 20:00:00.000000

A kept account is never purged or evicted, but still counts toward the
account cap (docs/policy/public-demo.md sections 8 and 9, digitva-xfxb).
Every existing row is not kept (server default false). Downgrade drops the
column, so the marks are lost and those accounts become purgeable again.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d8e2a6c4f1b7"
down_revision = "f3d9b5c7a2e4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_users",
        sa.Column("public_demo_keep", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("va_users", "public_demo_keep")
