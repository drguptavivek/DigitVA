"""Add the institute-admin flag to map_mentor_institute_user.

Additive: one boolean, default false, so every existing member stays plain
staff. The flag marks a member who may create and remove their own institute's
staff accounts (docs/policy/organization-model.md, "Mentoring institutes").
Downgrade drops the column.

Revision ID: d7e3a1c9b5f2
Revises: c4a9e7d2b6f1
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d7e3a1c9b5f2"
down_revision = "c4a9e7d2b6f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "map_mentor_institute_user",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("map_mentor_institute_user", "is_admin")
