"""Add coding_tester access role

Adds 'coding_tester' to access_role_enum and updates the role-scope check
constraint to permit coding_tester grants at project or project_site scope.

Revision ID: 678e498f2040
Revises: 9a8b7c6d5e4f
Create Date: 2026-04-10

"""
from alembic import op

revision = '678e498f2040'
down_revision = '9a8b7c6d5e4f'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE access_role_enum ADD VALUE IF NOT EXISTS 'coding_tester'")

    op.drop_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        """
        (role = 'admin' AND scope_type = 'global') OR
        (role = 'project_pi' AND scope_type = 'project') OR
        (role = 'site_pi' AND scope_type = 'project_site') OR
        (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager') AND scope_type IN ('project', 'project_site'))
        """,
    )


def downgrade():
    op.drop_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        """
        (role = 'admin' AND scope_type = 'global') OR
        (role = 'project_pi' AND scope_type = 'project') OR
        (role = 'site_pi' AND scope_type = 'project_site') OR
        (role IN ('collaborator', 'coder', 'reviewer', 'data_manager') AND scope_type IN ('project', 'project_site'))
        """,
    )
    # Note: PostgreSQL does not support removing enum values;
    # the 'coding_tester' value remains in access_role_enum after downgrade.
