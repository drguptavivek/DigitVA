"""Add mentoring institutes; allow site_pi at project_site scope only.

Additive tables mas_mentor_institute, map_mentor_institute_org_unit and
map_mentor_institute_user (docs/policy/organization-model.md, "Mentoring
institutes"). Also tightens ck_va_user_access_grants_role_scope so site_pi is
no longer allowed at org_unit scope. Existing org_unit site_pi grants are NOT
deleted: they are set to deactive with a note and stay for audit, and because
a CHECK cannot ignore them the new constraint is created NOT VALID when any
exist (enforced for every new or updated row, so none can be reactivated). Downgrade restores the old CHECK and drops the
new tables; it does not reactivate those grants.

Revision ID: c4a9e7d2b6f1
Revises: b8d2e5f1a7c3
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4a9e7d2b6f1"
down_revision = "b8d2e5f1a7c3"
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
ROLE_SCOPE_AFTER = ROLE_SCOPE_SHARED.format(site_pi="(role = 'site_pi' AND scope_type = 'project_site')")
ROLE_SCOPE_BEFORE = ROLE_SCOPE_SHARED.format(
    site_pi="(role = 'site_pi' AND scope_type IN ('project_site', 'org_unit'))"
)
NOTE = "deactivated by migration c4a9e7d2b6f1: site_pi is not held at unit scope"


def _now_col():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def _created_by():
    return sa.Column(
        "created_by_user_id",
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        nullable=True,
    )


def _replace_check(definition, *, not_valid=False):
    # Plain SQL with the full name: op.create_check_constraint would apply the
    # ck_ naming convention a second time (the doubling fd232fab5987 repaired).
    # NOT VALID keeps rows that predate the rule: a CHECK looks at role and
    # scope, never at grant_status, so a deactivated legacy row still violates
    # it. It stays unchecked until an operator deletes it and runs
    # ALTER TABLE va_user_access_grants VALIDATE CONSTRAINT <name>.
    op.execute(f'ALTER TABLE va_user_access_grants DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.execute(
        f'ALTER TABLE va_user_access_grants ADD CONSTRAINT "{CHECK_NAME}" '
        f"CHECK ({definition}){' NOT VALID' if not_valid else ''}"
    )


def upgrade():
    op.create_table(
        "mas_mentor_institute",
        sa.Column("institute_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("institute_code", sa.String(32), nullable=False),
        sa.Column("institute_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _now_col(),
        _created_by(),
        sa.UniqueConstraint("institute_code"),
    )
    op.create_table(
        "map_mentor_institute_org_unit",
        sa.Column(
            "institute_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("mas_mentor_institute.institute_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_unit_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("mas_org_unit.org_unit_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _now_col(),
        _created_by(),
    )
    op.create_index(
        "ix_map_mentor_institute_org_unit_unit", "map_mentor_institute_org_unit", ["org_unit_id"]
    )
    op.create_table(
        "map_mentor_institute_user",
        sa.Column(
            "institute_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("mas_mentor_institute.institute_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("va_users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _now_col(),
        _created_by(),
    )
    op.create_index("ix_map_mentor_institute_user_user", "map_mentor_institute_user", ["user_id"])

    # Keep the rows (audit); take them out of every resolver, then tighten.
    op.execute(
        sa.text(
            "UPDATE va_user_access_grants SET grant_status = 'deactive', "
            "notes = CASE WHEN notes IS NULL OR notes = '' THEN :note "
            "ELSE notes || ' | ' || :note END "
            "WHERE role = 'site_pi' AND scope_type = 'org_unit'"
        ).bindparams(note=NOTE)
    )
    legacy = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM va_user_access_grants "
            "WHERE role = 'site_pi' AND scope_type = 'org_unit'"
        )
    ).scalar_one()
    _replace_check(ROLE_SCOPE_AFTER, not_valid=bool(legacy))


def downgrade():
    _replace_check(ROLE_SCOPE_BEFORE)
    op.drop_table("map_mentor_institute_user")
    op.drop_table("map_mentor_institute_org_unit")
    op.drop_table("mas_mentor_institute")
