"""Add va_project_master.home_kpis_included.

Whether a project's aggregate counts appear on the public home page
(docs/policy/public-home-stats.md). Additive, default false: no project is
shown until an admin switches it on, and training or demo projects cannot be.

Revision ID: e4b7c2d9a6f1
Revises: 921a78710fbf
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e4b7c2d9a6f1"
down_revision = "921a78710fbf"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column("home_kpis_included", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("va_project_master", "home_kpis_included")
