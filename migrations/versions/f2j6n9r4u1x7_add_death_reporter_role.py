"""Add the death_reporter grant role and the can_report_deaths flag.

Revision ID: f2j6n9r4u1x7
Revises: e9h3k6p2s8v4
Create Date: 2026-10-06 20:00:00.000000

digitva-t6q (owner decisions 2026-10-01 and 2026-10-06). ANM and MPW at a
sub-centre and ASHA at a village register deaths but must not interview.
Additive and reversible:

- ``access_role_enum`` gains ``death_reporter``.
- ``ck_va_user_access_grants_role_scope`` allows it at ``org_unit`` scope
  only. The new CHECK is a superset of the old one, so every existing row
  passes it.
- ``map_org_level_cadre.can_report_deaths`` (default false), the fourth
  permission of the level x cadre grid. Data step: set it for ANM and MPW at
  the ``subcentre`` level and ASHA at the ``village`` level, only where those
  grid rows exist (the default template's codes, hardcoded: no application
  code is imported, docs/policy/migration-chaining.md).
- ``ix_va_death_register_registered_by`` (registered_by, updated_at,
  death_id): a reporter's own list, "registered by me, newest activity first".

Downgrade refuses while any ``death_reporter`` grant exists, rather than
deleting grants; it drops the flag (a setting, not data to keep) and the
index, and restores the CHECK. The enum value stays (PostgreSQL cannot drop
one).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f2j6n9r4u1x7"
down_revision = "e9h3k6p2s8v4"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_va_user_access_grants_role_scope"
ROLE_SCOPE_BEFORE = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'collaborator_pii', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit')) OR
    (role = 'interview_supervisor' AND scope_type = 'org_unit')
"""
ROLE_SCOPE_AFTER = ROLE_SCOPE_BEFORE.rstrip() + """ OR
    (role = 'death_reporter' AND scope_type = 'org_unit')
"""
INDEX_NAME = "ix_va_death_register_registered_by"


def _replace_check(definition):
    # Plain SQL with the full name: op.create_check_constraint would apply the
    # ck_ naming convention a second time (see c4a9e7d2b6f1).
    op.execute(f'ALTER TABLE va_user_access_grants DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.execute(f'ALTER TABLE va_user_access_grants ADD CONSTRAINT "{CHECK_NAME}" CHECK ({definition})')


def upgrade():
    # ADD VALUE must commit before the label can appear in the CHECK below.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE access_role_enum ADD VALUE IF NOT EXISTS 'death_reporter'")

    _replace_check(ROLE_SCOPE_AFTER)
    op.add_column(
        "map_org_level_cadre",
        sa.Column("can_report_deaths", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE map_org_level_cadre AS lc
        SET can_report_deaths = true
        FROM mas_org_level AS l, mas_cadre AS c
        WHERE lc.org_level_id = l.org_level_id
          AND lc.cadre_id = c.cadre_id
          AND ((l.level_code = 'subcentre' AND c.cadre_code IN ('ANM', 'MPW'))
               OR (l.level_code = 'village' AND c.cadre_code = 'ASHA'))
        """
    )
    op.create_index(INDEX_NAME, "va_death_register", ["registered_by", "updated_at", "death_id"])


def downgrade():
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM va_user_access_grants WHERE role = 'death_reporter'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} death_reporter grant(s) exist. Back them up and remove them "
            "before downgrading past f2j6n9r4u1x7. Nothing was changed."
        )
    op.drop_index(INDEX_NAME, table_name="va_death_register")
    op.drop_column("map_org_level_cadre", "can_report_deaths")
    _replace_check(ROLE_SCOPE_BEFORE)
    # The 'death_reporter' enum value stays: PostgreSQL cannot drop enum values.
