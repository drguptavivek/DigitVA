"""Index map_case_contact_attempts by attempted_at.

The area dashboard's per-staff view counts contact attempts of the last 30
days across a whole area (area_dashboard_service._interviewer_rows). The only
index covering attempted_at leads with death_id, so at a project root the
query had to probe every case in the area; this one lets it start from the
30-day window. Additive; downgrade drops it.

Revision ID: b8d2e5f1a7c3
Revises: a3f7c1e9d5b8
Create Date: 2026-09-30
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8d2e5f1a7c3"
down_revision = "a3f7c1e9d5b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_map_case_contact_attempts_attempted", "map_case_contact_attempts", ["attempted_at"]
    )


def downgrade():
    op.drop_index("ix_map_case_contact_attempts_attempted", table_name="map_case_contact_attempts")
