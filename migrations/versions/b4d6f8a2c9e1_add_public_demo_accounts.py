"""Public-demo accounts: username, marker and the own-case index (digitva-77v5.2).

Revision ID: b4d6f8a2c9e1
Revises: a3c5e7f9b2d4
Create Date: 2026-10-22

Additive (docs/policy/public-demo.md section 2):

- ``va_users.username``: a public-demo sign-in name, nullable, stored
  lower-case, unique (``uq_va_users_username``).
- ``va_users.is_public_demo``: NOT NULL, default false; partial index
  ``ix_va_users_public_demo_status`` on ``user_status`` where true (the
  sign-up cap and the purge).
- CHECK ``ck_va_users_email_or_mobile`` widened, same name: an account has an
  email, a sign-in mobile number or a username.
- ``ix_va_web_intake_drafts_user_submitted`` on ``(user_id, va_sid)`` where
  ``status = 'submitted'``: a demo user's own submissions, read by the
  own-case filter on every submission query.

Downgrade refuses while a username-only account exists (the narrow check
would reject it); otherwise it drops what upgrade added. No data changes.
"""

import sqlalchemy as sa
from alembic import op

revision = "b4d6f8a2c9e1"
down_revision = "a3c5e7f9b2d4"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_va_users_email_or_mobile"
NARROW = "email IS NOT NULL OR mobile_login IS NOT NULL"
WIDE = "email IS NOT NULL OR mobile_login IS NOT NULL OR username IS NOT NULL"


def upgrade():
    op.add_column("va_users", sa.Column("username", sa.String(length=30), nullable=True))
    op.add_column(
        "va_users",
        sa.Column("is_public_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("uq_va_users_username", "va_users", ["username"], unique=True)
    op.create_index(
        "ix_va_users_public_demo_status",
        "va_users",
        ["user_status"],
        postgresql_where=sa.text("is_public_demo"),
    )
    op.execute(f"ALTER TABLE va_users DROP CONSTRAINT {CHECK_NAME}")
    op.execute(f"ALTER TABLE va_users ADD CONSTRAINT {CHECK_NAME} CHECK ({WIDE})")
    op.create_index(
        "ix_va_web_intake_drafts_user_submitted",
        "va_web_intake_drafts",
        ["user_id", "va_sid"],
        postgresql_where=sa.text("status = 'submitted'"),
    )


def downgrade():
    bind = op.get_bind()
    username_only = bind.execute(sa.text(
        "SELECT count(*) FROM va_users WHERE email IS NULL AND mobile_login IS NULL"
    )).scalar_one()
    if username_only:
        raise RuntimeError(
            f"{username_only} account(s) have only a username; remove them before downgrading."
        )
    op.drop_index("ix_va_web_intake_drafts_user_submitted", table_name="va_web_intake_drafts")
    op.execute(f"ALTER TABLE va_users DROP CONSTRAINT {CHECK_NAME}")
    op.execute(f"ALTER TABLE va_users ADD CONSTRAINT {CHECK_NAME} CHECK ({NARROW})")
    op.drop_index("ix_va_users_public_demo_status", table_name="va_users")
    op.drop_index("uq_va_users_username", table_name="va_users")
    op.drop_column("va_users", "is_public_demo")
    op.drop_column("va_users", "username")
