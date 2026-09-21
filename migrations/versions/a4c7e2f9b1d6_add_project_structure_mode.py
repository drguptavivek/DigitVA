"""Explicit per-project structure mode: sites or organization.

Revision ID: a4c7e2f9b1d6
Revises: d5b71c3e9a84
Create Date: 2026-09-21 12:00:00.000000

digitva-67n. A project used to "use organization" implicitly, by having org
rows. The mode is now a column: 'sites' (the older Project > Site > Form
shape, the default) or 'organization' (a health-system unit tree). Policy:
docs/policy/organization-model.md ("Project structure mode").

Additive. Every existing project that already has any level or unit row is
backfilled to 'organization' so its tree stays editable; every other project
keeps the 'sites' server default. No row is deleted or changed otherwise.

The CHECK is added with raw SQL under its final name so the naming
convention in app/__init__.py cannot prefix it twice (see fd232fab5987).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4c7e2f9b1d6"
down_revision = "d5b71c3e9a84"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_va_project_master_project_structure_mode"


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "project_structure_mode",
            sa.String(length=16),
            nullable=False,
            server_default="sites",
        ),
    )
    op.execute(
        """
        UPDATE va_project_master p
           SET project_structure_mode = 'organization'
         WHERE EXISTS (SELECT 1 FROM mas_org_level l WHERE l.project_id = p.project_id)
            OR EXISTS (SELECT 1 FROM mas_org_unit u WHERE u.project_id = p.project_id)
        """
    )
    op.execute(
        f'ALTER TABLE va_project_master ADD CONSTRAINT "{CHECK_NAME}" '
        "CHECK (project_structure_mode IN ('sites', 'organization'))"
    )


def downgrade():
    op.execute(f'ALTER TABLE va_project_master DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.drop_column("va_project_master", "project_structure_mode")
