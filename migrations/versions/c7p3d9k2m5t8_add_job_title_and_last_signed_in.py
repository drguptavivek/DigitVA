"""Add va_users.job_title and va_users.last_signed_in_at.

Revision ID: c7p3d9k2m5t8
Revises: b4k8m2r6w9x3
Create Date: 2026-10-06 10:00:00.000000

``job_title`` (digitva-04u4): optional public free text naming a person's post;
never consulted for access. ``last_signed_in_at`` (digitva-ci8): set on every
completed web sign-in and device session opening; null until the next one.

Purely additive: two nullable columns, no default, no data rewritten. The
downgrade drops both (neither is the source of any other data).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7p3d9k2m5t8"
down_revision = "b4k8m2r6w9x3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("va_users", sa.Column("job_title", sa.String(length=120), nullable=True))
    op.add_column(
        "va_users", sa.Column("last_signed_in_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("va_users", "last_signed_in_at")
    op.drop_column("va_users", "job_title")
