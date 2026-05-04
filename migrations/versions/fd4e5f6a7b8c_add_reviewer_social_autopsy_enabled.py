"""add reviewer social autopsy enabled flag

Revision ID: fd4e5f6a7b8c
Revises: fc3d4e5f6a7b
Create Date: 2026-05-04 05:45:00.000000

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "fd4e5f6a7b8c"
down_revision = "fc3d4e5f6a7b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "reviewer_social_autopsy_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE va_project_master
            SET reviewer_social_autopsy_enabled = social_autopsy_enabled
            """
        )
    )


def downgrade():
    op.drop_column("va_project_master", "reviewer_social_autopsy_enabled")
