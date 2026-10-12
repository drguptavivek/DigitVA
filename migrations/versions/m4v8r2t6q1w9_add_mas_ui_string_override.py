"""Add mas_ui_string_override (digitva-fsjz).

Revision ID: m4v8r2t6q1w9
Revises: k8p4r2w6y3f1
Create Date: 2026-10-12 09:00:00.000000

A reader's correction to one Expo UI string in one locale, served to every
browser and phone without a new build (docs/policy/ui-strings.md). One row per
(locale_code, string_key); the key pair is the primary key.

Additive and reversible: a new, empty table. Downgrade never drops corrections
silently: it refuses while rows exist, as k8p4r2w6y3f1 does for its cases.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "m4v8r2t6q1w9"
down_revision = "k8p4r2w6y3f1"
branch_labels = None
depends_on = None

TABLE = "mas_ui_string_override"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("locale_code", sa.String(length=16), nullable=False),
        sa.Column("string_key", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["va_users.user_id"],
            name="fk_mas_ui_string_override_updated_by_va_users",
        ),
        sa.PrimaryKeyConstraint("locale_code", "string_key", name="pk_mas_ui_string_override"),
    )


def downgrade():
    remaining = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} UI string correction(s) exist; they are data and are not dropped. "
            "Revert them in the admin page before downgrading."
        )
    op.drop_table(TABLE)
