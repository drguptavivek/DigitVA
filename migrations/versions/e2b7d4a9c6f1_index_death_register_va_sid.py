"""Index va_death_register by va_sid.

The area dashboard's card joins cases to their submission for the median
days from death to interview and the cause period by date of death
(area_dashboard_service, docs/policy/area-dashboard.md). The only va_sid
indexes are partial (duplicates, ODK cases), so the join scanned the
register. Additive; downgrade drops it. Bead digitva-qfh8.

Revision ID: e2b7d4a9c6f1
Revises: c5e8a1f4b2d9
Create Date: 2026-10-22
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2b7d4a9c6f1"
down_revision = "c5e8a1f4b2d9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_va_death_register_va_sid", "va_death_register", ["va_sid"])


def downgrade():
    op.drop_index("ix_va_death_register_va_sid", table_name="va_death_register")
