"""Default va_project_master.web_intake_mode to 'direct' for new projects.

Revision ID: c7a3f9e1b5d2
Revises: b4e7c2a9d6f3
Create Date: 2026-10-29 12:00:00.000000

Owner decision 2026-10-29 (digitva-7amd.25, docs/policy/web-intake.md): a new
project collects in the browser and the Collect app unless an administrator
turns intake off. Only the column's server default changes; no existing row is
touched, so every current project keeps its setting. Downgrade restores 'off'
as the default, again without touching rows.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7a3f9e1b5d2"
down_revision = "b4e7c2a9d6f3"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "va_project_master",
        "web_intake_mode",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default="direct",
    )


def downgrade():
    op.alter_column(
        "va_project_master",
        "web_intake_mode",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default="off",
    )
