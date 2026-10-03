"""Sign-in by mobile number with server-generated passwords (digitva-l7c2).

docs/policy/mobile-sign-in.md. Additive:

- ``va_users.email`` becomes nullable (a mobile-only account has none; the
  unique constraint stays, and PostgreSQL allows many NULLs under it).
- ``va_users.mobile_login``: the canonical 10-digit sign-in number, UNIQUE.
- ``va_users.mobile_verified_at``: when a mobile-only account first redeemed
  a sign-in code.
- CHECK ``ck_va_users_email_or_mobile``: an account has one or the other.
- ``auth_mobile_codes``: one-time sign-in codes, stored only as keyed hashes,
  with a partial unique index allowing one live (unredeemed, unvoided) code
  per user.

Backfill sets ``mobile_login`` from the free-text ``phone`` only where the
canonical number (digits only, a leading ``0`` or ``91`` in front of ten
digits dropped, then exactly ten digits -- the DM lookup's rule) is held by
exactly one account. Shared and malformed numbers stay NULL and keep
signing in by email until corrected; ``phone`` is never modified.

Downgrade refuses while any account has no email: dropping ``mobile_login``
would leave such an account with no way to sign in, and restoring NOT NULL
on ``email`` would fail anyway.

Revision ID: f3a8c1d6e2b9
Revises: e2b7c4d9a1f3
Create Date: 2026-10-03
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a8c1d6e2b9"
down_revision = "e2b7c4d9a1f3"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_va_users_email_or_mobile"

# Same rule as app.services.user_account_service.PHONE_CANONICAL.
BACKFILL_SQL = r"""
WITH canon AS (
    SELECT user_id,
           regexp_replace(regexp_replace(phone, '[^0-9]', '', 'g'),
                          '^(0|91)([0-9]{10})$', '\2') AS mobile
    FROM va_users
    WHERE phone IS NOT NULL
),
unique_numbers AS (
    SELECT mobile FROM canon
    WHERE mobile ~ '^[0-9]{10}$'
    GROUP BY mobile
    HAVING count(*) = 1
)
UPDATE va_users AS u
SET mobile_login = c.mobile
FROM canon AS c
JOIN unique_numbers AS n ON n.mobile = c.mobile
WHERE u.user_id = c.user_id
"""


def upgrade():
    op.alter_column("va_users", "email", existing_type=sa.String(length=128), nullable=True)
    op.add_column("va_users", sa.Column("mobile_login", sa.String(length=10), nullable=True))
    op.add_column(
        "va_users",
        sa.Column("mobile_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("va_users_mobile_login_key", "va_users", ["mobile_login"])
    op.execute(BACKFILL_SQL)
    # Plain SQL with the full name: op.create_check_constraint would apply the
    # "ck_%(table_name)s_" naming convention on top of it.
    op.execute(
        f"ALTER TABLE va_users ADD CONSTRAINT {CHECK_NAME} "
        "CHECK (email IS NOT NULL OR mobile_login IS NOT NULL)"
    )

    op.create_table(
        "auth_mobile_codes",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_mobile_codes"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["va_users.user_id"],
            name="fk_auth_mobile_codes_user_id_va_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by"],
            ["va_users.user_id"],
            name="fk_auth_mobile_codes_issued_by_va_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_auth_mobile_codes_user_id", "auth_mobile_codes", ["user_id"])
    op.create_index(
        "ix_auth_mobile_codes_live_user",
        "auth_mobile_codes",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("redeemed_at IS NULL AND voided_at IS NULL"),
    )


def downgrade():
    bind = op.get_bind()
    mobile_only = bind.execute(
        sa.text("SELECT count(*) FROM va_users WHERE email IS NULL")
    ).scalar()
    if mobile_only:
        raise RuntimeError(
            f"{mobile_only} account(s) have no email and sign in by mobile only; "
            "give each an email before downgrading past f3a8c1d6e2b9."
        )
    op.drop_index("ix_auth_mobile_codes_live_user", table_name="auth_mobile_codes")
    op.drop_index("ix_auth_mobile_codes_user_id", table_name="auth_mobile_codes")
    op.drop_table("auth_mobile_codes")
    op.execute(f"ALTER TABLE va_users DROP CONSTRAINT {CHECK_NAME}")
    op.drop_constraint("va_users_mobile_login_key", "va_users", type_="unique")
    op.drop_column("va_users", "mobile_verified_at")
    op.drop_column("va_users", "mobile_login")
    op.alter_column("va_users", "email", existing_type=sa.String(length=128), nullable=False)
