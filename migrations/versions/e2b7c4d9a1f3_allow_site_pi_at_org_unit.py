"""Allow site_pi at org_unit scope: the In-charge (digitva-0wc stage 5).

Loosens ck_va_user_access_grants_role_scope so site_pi may be held at
org_unit as well as project_site (docs/policy/access-control-model.md,
"In-charge"). Additive: the new CHECK is a superset of the old one, so every
existing row passes it and it is created fully validated; project_site
site_pi rows are untouched, and the org_unit rows c4a9e7d2b6f1 deactivated
stay deactive.

Downgrade mirrors c4a9e7d2b6f1's upgrade: every active site_pi/org_unit grant
is set deactive with a note (kept for audit, never deleted), then the tight
CHECK returns, NOT VALID when such rows exist.

Revision ID: e2b7c4d9a1f3
Revises: d7e3a1c9b5f2
Create Date: 2026-10-03
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2b7c4d9a1f3"
down_revision = "d7e3a1c9b5f2"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_va_user_access_grants_role_scope"
ROLE_SCOPE_SHARED = """
    (role = 'admin' AND scope_type = 'global') OR
    (role = 'project_pi' AND scope_type = 'project') OR
    {site_pi} OR
    (role IN ('collaborator', 'collaborator_pii', 'coder', 'coding_tester', 'reviewer', 'data_manager', 'interviewer') AND scope_type IN ('project', 'project_site', 'org_unit')) OR
    (role = 'interview_supervisor' AND scope_type = 'org_unit')
"""
ROLE_SCOPE_IN_CHARGE = ROLE_SCOPE_SHARED.format(
    site_pi="(role = 'site_pi' AND scope_type IN ('project_site', 'org_unit'))"
)
ROLE_SCOPE_PAIR_ONLY = ROLE_SCOPE_SHARED.format(
    site_pi="(role = 'site_pi' AND scope_type = 'project_site')"
)
NOTE = "deactivated by downgrade of e2b7c4d9a1f3: site_pi is not held at unit scope"


def _replace_check(definition, *, not_valid=False):
    # Plain SQL with the full name: op.create_check_constraint would apply the
    # ck_ naming convention a second time (see c4a9e7d2b6f1).
    op.execute(f'ALTER TABLE va_user_access_grants DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.execute(
        f'ALTER TABLE va_user_access_grants ADD CONSTRAINT "{CHECK_NAME}" '
        f"CHECK ({definition}){' NOT VALID' if not_valid else ''}"
    )


def upgrade():
    _replace_check(ROLE_SCOPE_IN_CHARGE)


def downgrade():
    # Rows c4a9e7d2b6f1 already deactivated carry their own note; only live
    # In-charge grants are taken out of every resolver here.
    op.execute(
        sa.text(
            "UPDATE va_user_access_grants SET grant_status = 'deactive', "
            "notes = CASE WHEN notes IS NULL OR notes = '' THEN :note "
            "ELSE notes || ' | ' || :note END "
            "WHERE role = 'site_pi' AND scope_type = 'org_unit' AND grant_status = 'active'"
        ).bindparams(note=NOTE)
    )
    legacy = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM va_user_access_grants "
            "WHERE role = 'site_pi' AND scope_type = 'org_unit'"
        )
    ).scalar_one()
    _replace_check(ROLE_SCOPE_PAIR_ONLY, not_valid=bool(legacy))
