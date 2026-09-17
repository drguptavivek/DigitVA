"""Unit-scoped access grants: org_unit scope, org_unit_id, cadre_id.

Revision ID: d9e3f5a7b2c4
Revises: f4b8dd6e3568
Create Date: 2026-09-17 15:00:00.000000

Additive only. Adds the 'org_unit' value to access_scope_enum, two nullable
columns on va_user_access_grants, and widens the two scope check constraints
so unit-scoped grants are accepted. Existing grants are untouched and keep
their exact meaning: no existing row can become an org_unit grant, and no
role gains access it did not already have. Plan:
docs/planning/health-system-organization-model-plan.md (phase 2).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d9e3f5a7b2c4"
down_revision = "f4b8dd6e3568"
branch_labels = None
depends_on = None


SCOPE_SHAPE_BEFORE = """
    (scope_type = 'global' AND project_id IS NULL AND project_site_id IS NULL) OR
    (scope_type = 'project' AND project_id IS NOT NULL AND project_site_id IS NULL) OR
    (scope_type = 'project_site' AND project_id IS NULL AND project_site_id IS NOT NULL)
"""

SCOPE_SHAPE_AFTER = """
    (scope_type = 'global' AND project_id IS NULL AND project_site_id IS NULL AND org_unit_id IS NULL) OR
    (scope_type = 'project' AND project_id IS NOT NULL AND project_site_id IS NULL AND org_unit_id IS NULL) OR
    (scope_type = 'project_site' AND project_id IS NULL AND project_site_id IS NOT NULL AND org_unit_id IS NULL) OR
    (scope_type = 'org_unit' AND project_id IS NULL AND project_site_id IS NULL AND org_unit_id IS NOT NULL)
"""

ROLE_SCOPE_BEFORE = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type = 'project_site') OR
    (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager') AND scope_type IN ('project', 'project_site'))
"""

ROLE_SCOPE_AFTER = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager') AND scope_type IN ('project', 'project_site', 'org_unit'))
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
        op.execute("ALTER TYPE access_scope_enum ADD VALUE IF NOT EXISTS 'org_unit'")

    op.add_column(
        "va_user_access_grants",
        sa.Column("org_unit_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "va_user_access_grants",
        sa.Column("cadre_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_va_user_access_grants_org_unit",
        "va_user_access_grants",
        "mas_org_unit",
        ["org_unit_id"],
        ["org_unit_id"],
    )
    op.create_foreign_key(
        "fk_va_user_access_grants_cadre",
        "va_user_access_grants",
        "mas_cadre",
        ["cadre_id"],
        ["cadre_id"],
    )

    _drop_check("ck_va_user_access_grants_scope_shape")
    op.create_check_constraint(
        "ck_va_user_access_grants_scope_shape",
        "va_user_access_grants",
        SCOPE_SHAPE_AFTER,
    )
    _drop_check("ck_va_user_access_grants_role_scope")
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        ROLE_SCOPE_AFTER,
    )
    op.create_check_constraint(
        "ck_va_user_access_grants_cadre_scope",
        "va_user_access_grants",
        "cadre_id IS NULL OR scope_type = 'org_unit'",
    )

    op.create_index(
        "uq_va_user_access_grants_org_unit",
        "va_user_access_grants",
        ["user_id", "role", "org_unit_id"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'org_unit'"),
    )
    op.create_index(
        "ix_va_user_access_grants_org_unit_lookup",
        "va_user_access_grants",
        ["org_unit_id", "role", "grant_status"],
    )


def downgrade():
    # Unit-scoped grants cannot satisfy the pre-existing shape constraint, so
    # the downgrade refuses rather than deleting authorization rows on its own.
    # The operator decides what happens to them. The 'org_unit' enum label
    # stays either way: PostgreSQL cannot remove an enum value.
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM va_user_access_grants WHERE scope_type = 'org_unit'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} unit-scoped grant(s) exist. Back them up and remove them "
            "(DELETE FROM va_user_access_grants WHERE scope_type = 'org_unit') "
            "before downgrading past d9e3f5a7b2c4."
        )

    op.drop_index("ix_va_user_access_grants_org_unit_lookup", "va_user_access_grants")
    op.drop_index("uq_va_user_access_grants_org_unit", "va_user_access_grants")

    _drop_check("ck_va_user_access_grants_cadre_scope")
    _drop_check("ck_va_user_access_grants_role_scope")
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        ROLE_SCOPE_BEFORE,
    )
    _drop_check("ck_va_user_access_grants_scope_shape")
    op.create_check_constraint(
        "ck_va_user_access_grants_scope_shape",
        "va_user_access_grants",
        SCOPE_SHAPE_BEFORE,
    )

    op.drop_constraint(
        "fk_va_user_access_grants_cadre", "va_user_access_grants", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_va_user_access_grants_org_unit", "va_user_access_grants", type_="foreignkey"
    )
    op.drop_column("va_user_access_grants", "cadre_id")
    op.drop_column("va_user_access_grants", "org_unit_id")
