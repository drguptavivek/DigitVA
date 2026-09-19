"""Instrument display locales and their translated strings.

Revision ID: a7d4f1c9b0e6
Revises: c3e8b5a1f4d2
Create Date: 2026-09-19 18:00:00.000000

WP6 of docs/planning/web-capture-project-configuration-plan.md. Translations
become server data: a locale is a row, its strings are rows, and a frontend
fetches them by instrument, locale and version rather than having them baked
into a bundle.

- ``mas_instrument_locales`` — one row per (instrument, locale). ``is_active``
  starts false: a locale is served to forms only once an import reaches the
  coverage threshold. ``version`` is what a client revalidates against.
- ``map_instrument_translations`` — one row per translated string, keyed by the
  five columns the importer upserts on. The key names an item the curated
  reference form already has; nothing here can create a question.

``en`` is the base locale of every bundled instrument. It needs no rows in
either table and is always served, so this migration seeds nothing.

Purely additive: two new tables, no existing column touched, no data rewritten.
The downgrade drops both, losing imported translations — re-importable from the
documented source workbooks, which is why that cost is acceptable.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7d4f1c9b0e6"
down_revision = "c3e8b5a1f4d2"
branch_labels = None
depends_on = None

LOCALES = "mas_instrument_locales"
TRANSLATIONS = "map_instrument_translations"


def upgrade():
    op.create_table(
        LOCALES,
        sa.Column("instrument_code", sa.String(32), nullable=False),
        sa.Column("locale_code", sa.String(16), nullable=False),
        sa.Column("language_name", sa.String(64), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("source_document", sa.String(255), nullable=True),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "instrument_code", "locale_code", name="pk_mas_instrument_locales"
        ),
    )
    op.create_table(
        TRANSLATIONS,
        sa.Column("instrument_code", sa.String(32), nullable=False),
        sa.Column("locale_code", sa.String(16), nullable=False),
        sa.Column("item_kind", sa.String(16), nullable=False),
        sa.Column("item_key", sa.String(255), nullable=False),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "source", sa.String(16), nullable=False, server_default="imported"
        ),
        sa.Column("updated_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "instrument_code",
            "locale_code",
            "item_kind",
            "item_key",
            "field",
            name="pk_map_instrument_translations",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_code", "locale_code"],
            [f"{LOCALES}.instrument_code", f"{LOCALES}.locale_code"],
            name="fk_map_instrument_translations_locale",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["va_users.user_id"],
            name="fk_map_instrument_translations_updated_by_va_users",
        ),
    )


def downgrade():
    op.drop_table(TRANSLATIONS)
    op.drop_table(LOCALES)
