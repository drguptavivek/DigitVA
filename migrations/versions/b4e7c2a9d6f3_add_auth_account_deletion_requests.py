"""Add auth_account_deletion_requests: a staff account's own deletion request.

Revision ID: b4e7c2a9d6f3
Revises: d8e2a6c4f1b7
Create Date: 2026-10-27 22:00:00.000000

The signed-in app or website files one for admins to review; deletion stays
manual (docs/policy/public-privacy-and-data-requests.md section 8,
digitva-et16). One pending request per account: a partial unique index on
``user_id`` where ``handled_at`` is NULL. Additive; downgrade drops the table,
losing only the requests (each is also a security event).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4e7c2a9d6f3"
down_revision = "d8e2a6c4f1b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_account_deletion_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_via", sa.String(length=8), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["va_users.user_id"], ondelete="CASCADE",
            name=op.f("fk_auth_account_deletion_requests_user_id_va_users"),
        ),
        sa.ForeignKeyConstraint(
            ["handled_by"], ["va_users.user_id"], ondelete="SET NULL",
            name=op.f("fk_auth_account_deletion_requests_handled_by_va_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_account_deletion_requests")),
    )
    op.create_index(
        "uq_auth_account_deletion_requests_pending_user",
        "auth_account_deletion_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("handled_at IS NULL"),
    )
    op.create_index(
        "ix_auth_account_deletion_requests_pending",
        "auth_account_deletion_requests",
        ["requested_at"],
        postgresql_where=sa.text("handled_at IS NULL"),
    )


def downgrade():
    op.drop_index("ix_auth_account_deletion_requests_pending", table_name="auth_account_deletion_requests")
    op.drop_index("uq_auth_account_deletion_requests_pending_user", table_name="auth_account_deletion_requests")
    op.drop_table("auth_account_deletion_requests")
