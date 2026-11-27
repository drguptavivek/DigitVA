"""Mark a date of death stored from a year-only answer (digitva-xmlw).

A year-only date of death is stored as 1 July of that year
(``web_intake.drafts._approximate_date_of_death``); this flag tells it from a
real 1 July death. Nullable, no default, no backfill: an existing row stays
NULL (not known), every writer that sets the date sets the flag with it.

Revision ID: a40477e55b72
Revises: f3c9d1a7b5e2
Create Date: 2026-11-27
"""

import sqlalchemy as sa
from alembic import op

revision = "a40477e55b72"
down_revision = "f3c9d1a7b5e2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_death_register",
        sa.Column("date_of_death_year_only", sa.Boolean(), nullable=True),
    )


def downgrade():
    op.drop_column("va_death_register", "date_of_death_year_only")
