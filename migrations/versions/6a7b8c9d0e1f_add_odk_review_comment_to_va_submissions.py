"""add odk review comments to va_submissions

Revision ID: 6a7b8c9d0e1f
Revises: 5f2c1a9d7b4e
Create Date: 2026-03-18 18:45:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "6a7b8c9d0e1f"
down_revision = "5f2c1a9d7b4e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("va_submissions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("va_odk_reviewcomments", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("va_submissions", schema=None) as batch_op:
        batch_op.drop_column("va_odk_reviewcomments")
