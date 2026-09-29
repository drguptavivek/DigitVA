"""Name the grant and cadre a supervisor action relied on in map_case_transitions.

Decision 15 of .tasks/2026-09-28-interviewer-worklist.md: every supervisor
action's audit row names the grant and the cadre relied on. Two nullable
columns with foreign keys; existing rows and team moves stay NULL. Nothing
filters on them, so no index. Additive; downgrade drops both columns.

Revision ID: a8d4f1c7e3b9
Revises: f2a6d9c3e8b1
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a8d4f1c7e3b9"
down_revision = "f2a6d9c3e8b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("map_case_transitions", sa.Column("authorizing_grant_id", sa.Uuid(), nullable=True))
    op.add_column("map_case_transitions", sa.Column("authorizing_cadre_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_map_case_transitions_authorizing_grant",
        "map_case_transitions", "va_user_access_grants", ["authorizing_grant_id"], ["grant_id"],
    )
    op.create_foreign_key(
        "fk_map_case_transitions_authorizing_cadre",
        "map_case_transitions", "mas_cadre", ["authorizing_cadre_id"], ["cadre_id"],
    )


def downgrade():
    op.drop_constraint("fk_map_case_transitions_authorizing_cadre", "map_case_transitions", type_="foreignkey")
    op.drop_constraint("fk_map_case_transitions_authorizing_grant", "map_case_transitions", type_="foreignkey")
    op.drop_column("map_case_transitions", "authorizing_cadre_id")
    op.drop_column("map_case_transitions", "authorizing_grant_id")
