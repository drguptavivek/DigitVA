"""Add map_instrument_translation_suggestions.

Revision ID: g3k7n1s5v9y2
Revises: g3k7o1s5w9a2
Create Date: 2026-10-06 21:00:00.000000

digitva-5op (owner decision 2026-10-06). District staff granted on a project
suggest a wording for one instrument translation string; an administrator or
that project's PI accepts or rejects it. One row per suggestion, carrying who
suggested and who decided; ``seen_text`` is the served translation the
suggester saw, so an accept can refuse when the string changed since.

Additive and reversible: a new, empty table. Downgrade drops it, which loses
the suggestions (accepted ones are already in ``map_instrument_translations``).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "g3k7n1s5v9y2"
down_revision = "g3k7o1s5w9a2"
branch_labels = None
depends_on = None

TABLE = "map_instrument_translation_suggestions"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("instrument_code", sa.String(length=32), nullable=False),
        sa.Column("locale_code", sa.String(length=16), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_key", sa.String(length=255), nullable=False),
        sa.Column("field", sa.String(length=32), nullable=False),
        sa.Column("proposed_text", sa.Text(), nullable=False),
        sa.Column("seen_text", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("suggested_by", sa.Uuid(), nullable=False),
        sa.Column("suggested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_code", "locale_code"],
            ["mas_instrument_locales.instrument_code", "mas_instrument_locales.locale_code"],
            name="fk_mits_locale",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"], name="fk_mits_project"),
        sa.ForeignKeyConstraint(["suggested_by"], ["va_users.user_id"], name="fk_mits_suggested_by"),
        sa.ForeignKeyConstraint(["decided_by"], ["va_users.user_id"], name="fk_mits_decided_by"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="status"),
        sa.CheckConstraint(
            "status = 'pending' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="decided_has_decider",
        ),
    )
    op.create_index("ix_mits_locale_status", TABLE, ["instrument_code", "locale_code", "status", "id"])
    op.create_index("ix_mits_project_status", TABLE, ["project_id", "status", "id"])
    op.create_index(
        "uq_mits_pending_per_user",
        TABLE,
        ["suggested_by", "instrument_code", "locale_code", "item_kind", "item_key", "field"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_index("uq_mits_pending_per_user", table_name=TABLE)
    op.drop_index("ix_mits_project_status", table_name=TABLE)
    op.drop_index("ix_mits_locale_status", table_name=TABLE)
    op.drop_table(TABLE)
