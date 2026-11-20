"""Add va_consent_withdrawals and va_death_register.consent_withdrawn_at.

Revision ID: f4c2a8e6b1d9
Revises: e3b7c9d1f5a2
Create Date: 2026-11-20

Additive (digitva-4gu7, docs/policy/consent-withdrawal.md): a respondent's
consent withdrawal recorded on a submitted case. The nullable register column
mirrors the active withdrawal so the shared exclusion rule
(app/services/duplicate_exclusion.py) reads it without a join; no existing row
changes. The analytics materialized views do not inline the rule (it is applied
at query time), so none is rebuilt. Downgrade drops the column and the table
with its rows: withdrawn cases would come back everywhere, so take a backup of
va_consent_withdrawals first.
"""

import sqlalchemy as sa
from alembic import op

revision = "f4c2a8e6b1d9"
down_revision = "e3b7c9d1f5a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_death_register", sa.Column("consent_withdrawn_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "va_consent_withdrawals",
        sa.Column("withdrawal_id", sa.Uuid(), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("requested_on", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("contact_reference", sa.String(length=100), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_by", sa.Uuid(), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undo_reason", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "channel IN ('contact_form', 'phone', 'in_person', 'email', 'other')",
            name=op.f("ck_va_consent_withdrawals_channel"),
        ),
        sa.ForeignKeyConstraint(
            ["death_id"], ["va_death_register.death_id"],
            name="fk_va_consent_withdrawals_death_id_va_death_register",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["va_users.user_id"], name="fk_va_consent_withdrawals_recorded_by_va_users",
        ),
        sa.ForeignKeyConstraint(
            ["undone_by"], ["va_users.user_id"], name="fk_va_consent_withdrawals_undone_by_va_users",
        ),
        sa.PrimaryKeyConstraint("withdrawal_id", name="pk_va_consent_withdrawals"),
    )
    op.create_index(
        "uq_va_consent_withdrawals_active_death", "va_consent_withdrawals", ["death_id"], unique=True,
        postgresql_where=sa.text("undone_at IS NULL"),
    )


def downgrade():
    op.drop_index("uq_va_consent_withdrawals_active_death", table_name="va_consent_withdrawals")
    op.drop_table("va_consent_withdrawals")
    op.drop_column("va_death_register", "consent_withdrawn_at")
