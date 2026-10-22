"""Index va_users.user_created_at for the Users page grant grid.

Revision ID: a3c5e7f9b2d4
Revises: f6b2d8a4c1e7
Create Date: 2026-10-22

Additive: the admin grant grid (digitva-cgmc) filters accounts by created
date and sorts newest first. Downgrade drops the index; no data changes.
"""

from alembic import op

revision = "a3c5e7f9b2d4"
down_revision = "f6b2d8a4c1e7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_va_users_user_created_at", "va_users", ["user_created_at"])


def downgrade():
    op.drop_index("ix_va_users_user_created_at", table_name="va_users")
