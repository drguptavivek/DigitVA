"""widen va submissions audit byrole

Revision ID: 9f1a2b3c4d5e
Revises: 8b9c0d1e2f34
Create Date: 2026-03-18 23:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f1a2b3c4d5e"
down_revision = "8b9c0d1e2f34"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "va_submissions_auditlog",
        "va_audit_byrole",
        existing_type=sa.String(length=8),
        type_=sa.String(length=30),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "va_submissions_auditlog",
        "va_audit_byrole",
        existing_type=sa.String(length=30),
        type_=sa.String(length=8),
        existing_nullable=False,
    )
