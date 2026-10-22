"""Consent notice approval (legal review) per notice version.

Revision ID: d4a7c9e2f5b1
Revises: c8e4a2f6b1d3
Create Date: 2026-10-22

digitva-athy, owner decision 2026-10-22: a notice version is "Pending legal
review" until an admin approves it; the consent screen works either way.
``approved_at`` / ``approved_by`` on ``mas_consent_notice_versions``, NULL
meaning pending. Additive: every existing version stays pending (staging has
none). Downgrade drops both columns; the approval history stays in
``map_consent_audit`` (``consent_notice_approved``).
"""

import sqlalchemy as sa
from alembic import op

revision = "d4a7c9e2f5b1"
down_revision = "c8e4a2f6b1d3"
branch_labels = None
depends_on = None

TABLE = "mas_consent_notice_versions"
FK_NAME = "fk_mas_consent_notice_versions_approved_by_va_users"


def upgrade():
    op.add_column(TABLE, sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("approved_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(FK_NAME, TABLE, "va_users", ["approved_by"], ["user_id"])


def downgrade():
    op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")
    op.drop_column(TABLE, "approved_by")
    op.drop_column(TABLE, "approved_at")
