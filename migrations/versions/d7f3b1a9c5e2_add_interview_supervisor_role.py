"""Add the interview_supervisor grant role and the can_supervise_interviews flag.

Revision ID: d7f3b1a9c5e2
Revises: c4e8a2f6b9d3
Create Date: 2026-09-30 18:00:00.000000

digitva-vzk.5 (decisions 12, 15 and 16 in
.tasks/2026-09-28-interviewer-worklist.md). Additive and reversible:

- ``access_role_enum`` gains ``interview_supervisor``.
- ``ck_va_user_access_grants_role_scope`` allows it at ``org_unit`` scope
  only (decision 16).
- ``map_org_level_cadre.can_supervise_interviews`` (default false), the third
  permission of the level x cadre grid (decision 12).

Downgrade refuses while any ``interview_supervisor`` grant exists, rather
than deleting grants; the enum value stays (PostgreSQL cannot drop one).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d7f3b1a9c5e2"
down_revision = "c4e8a2f6b9d3"
branch_labels = None
depends_on = None

# Bare discriminator: the naming convention adds the ck_<table>_ prefix
# (see 120f783ea138 for the doubled-name bug this avoids).
CONSTRAINT_NAME = "ck_va_user_access_grants_role_scope"
CONSTRAINT_DISCRIMINATOR = "role_scope"

ROLE_SCOPE_BEFORE = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'collaborator_pii', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit'))
"""
ROLE_SCOPE_AFTER = ROLE_SCOPE_BEFORE.rstrip() + """ OR
    (role = 'interview_supervisor' AND scope_type = 'org_unit')
"""


def _replace_role_scope(definition: str) -> None:
    op.execute(f'ALTER TABLE va_user_access_grants DROP CONSTRAINT IF EXISTS "{CONSTRAINT_NAME}"')
    op.create_check_constraint(CONSTRAINT_DISCRIMINATOR, "va_user_access_grants", definition)


def upgrade():
    # ADD VALUE must commit before the label can appear in the CHECK below.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE access_role_enum ADD VALUE IF NOT EXISTS 'interview_supervisor'")

    _replace_role_scope(ROLE_SCOPE_AFTER)
    op.add_column(
        "map_org_level_cadre",
        sa.Column("can_supervise_interviews", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM va_user_access_grants WHERE role = 'interview_supervisor'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} interview_supervisor grant(s) exist. Back them up and remove them "
            "before downgrading past d7f3b1a9c5e2. Nothing was changed."
        )
    op.drop_column("map_org_level_cadre", "can_supervise_interviews")
    _replace_role_scope(ROLE_SCOPE_BEFORE)
    # The 'interview_supervisor' enum value stays: PostgreSQL cannot drop enum values.
