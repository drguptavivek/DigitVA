"""Add mas_ui_locale: the UI languages an admin publishes to the app.

Revision ID: 921a78710fbf
Revises: d3c8e5a1f7b4
Create Date: 2026-11-06 12:00:00.000000

One row per UI language (digitva-s028, docs/policy/ui-strings.md, "Publishing
a UI language"): native name, BCP 47 tag, direction and the published flag
that lets /api/v1/ui-strings list and serve the language. Hindi is seeded
published, because its corrections were served unconditionally before this
gate; nothing else is published. Downgrade drops the table; the served packs
then stop until the gate is back, and no string text is lost (it lives in
mas_ui_string_override and the bundle).
"""

import sqlalchemy as sa
from alembic import op

revision = "921a78710fbf"
down_revision = "d3c8e5a1f7b4"
branch_labels = None
depends_on = None

TABLE = "mas_ui_locale"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("locale_code", sa.String(length=16), nullable=False),
        sa.Column("native_name", sa.String(length=64), nullable=False),
        sa.Column("bcp47_tag", sa.String(length=35), nullable=False),
        sa.Column("direction", sa.String(length=3), server_default="ltr", nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("direction IN ('ltr', 'rtl')", name=op.f("ck_mas_ui_locale_direction")),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["va_users.user_id"], name=op.f("fk_mas_ui_locale_updated_by_va_users")
        ),
        sa.PrimaryKeyConstraint("locale_code", name=op.f("pk_mas_ui_locale")),
    )
    op.execute(
        "INSERT INTO mas_ui_locale (locale_code, native_name, bcp47_tag, direction, is_published) "
        "VALUES ('hi', 'हिन्दी', 'hi-IN', 'ltr', true)"
    )


def downgrade():
    op.drop_table(TABLE)
