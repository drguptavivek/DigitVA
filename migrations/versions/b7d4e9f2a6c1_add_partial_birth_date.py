"""Keep a partial birth date without fabricating a day or month.

Revision ID: b7d4e9f2a6c1
Revises: f3a8c1d6e2b9
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d4e9f2a6c1"
down_revision = "f3a8c1d6e2b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_death_register",
        sa.Column("date_of_birth_partial", sa.String(length=7), nullable=True),
    )
    op.create_check_constraint(
        "date_of_birth_partial_format",
        "va_death_register",
        "date_of_birth_partial IS NULL OR "
        "date_of_birth_partial ~ '^[0-9]{4}(-((0[1-9])|(1[0-2])))?$'",
    )
    op.create_check_constraint(
        "date_of_birth_exact_or_partial",
        "va_death_register",
        "date_of_birth IS NULL OR date_of_birth_partial IS NULL",
    )


def downgrade():
    # op.f(): the full name is already prefixed; a bare string would get the
    # naming convention's "ck_<table>_" a second time.
    op.drop_constraint(
        op.f("ck_va_death_register_date_of_birth_exact_or_partial"),
        "va_death_register",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_va_death_register_date_of_birth_partial_format"),
        "va_death_register",
        type_="check",
    )
    op.drop_column("va_death_register", "date_of_birth_partial")
