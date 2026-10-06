"""Add map_org_level_cadre.default_roles.

Revision ID: g3k7o1s5w9a2
Revises: f2j6n9r4u1x7
Create Date: 2026-10-06 22:00:00.000000

digitva-vjt (owner decision 2026-10-06). Each level x cadre grid row stores
the unit-scope roles pre-ticked when a person of that cadre is granted at that
level. Additive and reversible:

- ``default_roles`` is ``varchar[]``, not null, default empty, so every
  existing row starts with no defaults. No data step: new grids take their
  defaults from the application's seed template; an existing grid is never
  rewritten.
- The CHECK limits the array to the unit-scope roles (the roles a unit grant
  may carry, hardcoded here: no application code is imported,
  docs/policy/migration-chaining.md). The rule that a role needing a cadre
  flag only appears while the flag is set is the application's, applied when
  the row is saved.

Downgrade drops the column; defaults are a setting, not data to keep. Grants
written from them are ordinary grants and stay.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# revision identifiers, used by Alembic.
revision = "g3k7o1s5w9a2"
down_revision = "f2j6n9r4u1x7"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_map_org_level_cadre_default_roles_unit_roles"
UNIT_ROLES = (
    "site_pi", "collaborator", "collaborator_pii", "coder", "coding_tester",
    "reviewer", "data_manager", "interviewer", "interview_supervisor", "death_reporter",
)


def upgrade():
    op.add_column(
        "map_org_level_cadre",
        sa.Column("default_roles", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
    )
    # Plain SQL with the full name: op.create_check_constraint would apply the
    # ck_ naming convention a second time (see c4a9e7d2b6f1).
    roles = ", ".join(f"'{role}'" for role in UNIT_ROLES)
    op.execute(
        f'ALTER TABLE map_org_level_cadre ADD CONSTRAINT "{CHECK_NAME}" '
        f"CHECK (default_roles <@ ARRAY[{roles}]::varchar[])"
    )


def downgrade():
    op.execute(f'ALTER TABLE map_org_level_cadre DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.drop_column("map_org_level_cadre", "default_roles")
