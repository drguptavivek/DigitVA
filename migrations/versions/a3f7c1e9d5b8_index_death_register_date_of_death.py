"""Index va_death_register by project and date of death.

The possible-duplicate check (web_intake_service.possible_duplicates) looks
for other cases in the same project whose date of death is within three
days; this index serves that window. Additive; downgrade drops it.

Revision ID: a3f7c1e9d5b8
Revises: f2c6a8d4b1e9
Create Date: 2026-09-30
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f7c1e9d5b8"
down_revision = "f2c6a8d4b1e9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_va_death_register_project_dod", "va_death_register", ["project_id", "date_of_death"]
    )


def downgrade():
    op.drop_index("ix_va_death_register_project_dod", table_name="va_death_register")
