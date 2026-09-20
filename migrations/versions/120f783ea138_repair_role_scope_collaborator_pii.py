"""Repair ck_va_user_access_grants_role_scope where it omits collaborator_pii.

Revision ID: 120f783ea138
Revises: f2031819b3aa
Create Date: 2026-09-20

digitva-88e: f1c6a9d3e7b5 already widened this constraint (and added the enum
label) to include 'collaborator_pii', but the dev database's constraint and
enum do not match -- pg_get_constraintdef and access_role_enum's members on
dev show the pre-f1c6a9d3e7b5 state even though dev is stamped long past that
revision (f1c6a9d3e7b5 is the root of dev's recorded chain per handoff.md).
So both were recreated or altered on dev outside the migration chain at some
point; this is operational drift, not a missing migration (see digitva-88e's
NOTES).

Alembic has no record of dev's out-of-band change to replay against, so this
migration cannot simply reapply f1c6a9d3e7b5 -- it instead reads the
constraint's current definition and only touches it when it differs from
what the models declare, making it a no-op on a fresh install (which already
has the six-role list) and a real repair on dev (or any other database that
independently drifted the same way). The enum repair uses ADD VALUE IF NOT
EXISTS, which is already a no-op on a fresh install by construction.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "120f783ea138"
down_revision = "f2031819b3aa"
branch_labels = None
depends_on = None

# The clean, undoubled name fd232fab5987 left in the database -- used for the
# raw-SQL lookup/drop below. op.create_check_constraint gets only the bare
# discriminator ("role_scope"): the naming convention in app/__init__.py
# (ck_%(table_name)s_%(constraint_name)s) applies it automatically, and
# passing the already-prefixed form doubles it -- the exact mistake b3e55cd
# and fd232fab5987 fixed for this same constraint.
CONSTRAINT_NAME = "ck_va_user_access_grants_role_scope"
CONSTRAINT_DISCRIMINATOR = "role_scope"

ROLE_SCOPE_CURRENT = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'collaborator_pii', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit'))
"""

ROLE_SCOPE_WITHOUT_COLLABORATOR_PII = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    (role = 'site_pi' AND scope_type IN ('project_site', 'org_unit')) OR
    (role IN ('collaborator', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit'))
"""


def _current_definition(conn):
    return conn.execute(
        sa.text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'va_user_access_grants'::regclass AND conname = :name"
        ),
        {"name": CONSTRAINT_NAME},
    ).scalar_one_or_none()


def upgrade():
    # ALTER TYPE ... ADD VALUE must commit before the new label can be used
    # in a check constraint below, so it runs outside the migration's
    # transaction (same reason f1c6a9d3e7b5 does this). IF NOT EXISTS makes
    # it a no-op wherever the label is already present.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE access_role_enum ADD VALUE IF NOT EXISTS 'collaborator_pii'"
        )

    conn = op.get_bind()
    definition = _current_definition(conn)
    if definition is not None and "collaborator_pii" not in definition:
        op.execute(
            f'ALTER TABLE va_user_access_grants DROP CONSTRAINT IF EXISTS "{CONSTRAINT_NAME}"'
        )
        op.create_check_constraint(
            CONSTRAINT_DISCRIMINATOR, "va_user_access_grants", ROLE_SCOPE_CURRENT
        )
    # definition is None (constraint missing entirely) or already correct:
    # nothing to do -- an absent constraint is a different defect than the
    # one this migration repairs, and forcing one into existence here would
    # hide that a database is missing f1c6a9d3e7b5 outright.


def downgrade():
    conn = op.get_bind()
    remaining = conn.execute(
        sa.text(
            "SELECT count(*) FROM va_user_access_grants WHERE role = 'collaborator_pii'"
        )
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} collaborator_pii grant(s) exist. Back them up and remove "
            "them before downgrading past 120f783ea138."
        )
    definition = _current_definition(conn)
    if definition is not None and "collaborator_pii" in definition:
        op.execute(
            f'ALTER TABLE va_user_access_grants DROP CONSTRAINT IF EXISTS "{CONSTRAINT_NAME}"'
        )
        op.create_check_constraint(
            CONSTRAINT_DISCRIMINATOR,
            "va_user_access_grants",
            ROLE_SCOPE_WITHOUT_COLLABORATOR_PII,
        )
