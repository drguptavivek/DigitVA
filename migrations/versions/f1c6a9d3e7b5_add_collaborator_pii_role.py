"""Add the collaborator_pii role.

Revision ID: f1c6a9d3e7b5
Revises: 2e1da5fbaa0a
Create Date: 2026-09-18 00:00:00.000000

Additive only. Adds the 'collaborator_pii' value to access_role_enum and
widens ck_va_user_access_grants_role_scope so it is permitted at the same
scopes as 'collaborator' (project, project_site, org_unit) -- never
'global', which stays reserved for 'admin'.

No existing grant is touched: this migration does not convert any
'collaborator' row to 'collaborator_pii'. Whether an existing collaborator
should also see personal data is a per-person decision for an admin or
project PI to make later, granted explicitly. See
docs/policy/access-control-model.md ("collaborator_pii") and
.tasks/viewer-pii-roles.md.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f1c6a9d3e7b5"
down_revision = "2e1da5fbaa0a"
branch_labels = None
depends_on = None


ROLE_SCOPE_BEFORE = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit'))
"""

ROLE_SCOPE_AFTER = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'collaborator_pii', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit'))
"""


def _drop_check(name: str) -> None:
    """Drop a check constraint by either spelling it may carry.

    The metadata naming convention ('ck_%(table_name)s_%(constraint_name)s')
    prefixes the table name onto whatever name a migration passes, so
    constraints created by an older migration carry the bare name while ones
    recreated today carry the doubled one. Dropping both keeps this migration
    rerunnable on every database.
    """
    for candidate in (name, f"ck_va_user_access_grants_{name}"):
        op.execute(
            f'ALTER TABLE va_user_access_grants DROP CONSTRAINT IF EXISTS "{candidate}"'
        )


def upgrade():
    # ALTER TYPE ... ADD VALUE must commit before the new label can be used in
    # a check constraint, so it runs outside the migration's transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE access_role_enum ADD VALUE IF NOT EXISTS 'collaborator_pii'"
        )

    _drop_check("ck_va_user_access_grants_role_scope")
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        ROLE_SCOPE_AFTER,
    )


def downgrade():
    # Refuse rather than silently discard authorization rows: any
    # collaborator_pii grant cannot satisfy the pre-existing role/scope
    # constraint. The 'collaborator_pii' enum label stays either way --
    # PostgreSQL cannot remove an enum value.
    remaining = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM va_user_access_grants WHERE role = 'collaborator_pii'"
        )
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} collaborator_pii grant(s) exist. Back them up and remove "
            "them (DELETE FROM va_user_access_grants WHERE role = 'collaborator_pii') "
            "before downgrading past f1c6a9d3e7b5."
        )

    _drop_check("ck_va_user_access_grants_role_scope")
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        ROLE_SCOPE_BEFORE,
    )
