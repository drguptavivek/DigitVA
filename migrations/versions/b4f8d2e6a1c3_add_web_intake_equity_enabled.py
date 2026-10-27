"""Add web_intake_equity_enabled to va_project_master.

Revision ID: b4f8d2e6a1c3
Revises: a9e4c7f2b3d6
Create Date: 2026-10-27 12:00:00.000000

``equity`` becomes a named extension in ``enabled_extensions`` (owner
decisions 2026-10-27, docs/policy/digitva-who-form-overrides.md, "Equity
extension"): residence_type, social_group, vulnerable_group, health_coverage
and the refusal profile. The default is ``false`` because the layer is off
unless a project enables it, so no existing project's questionnaire changes.

Purely additive: one new column, no existing column touched, no data
rewritten. The downgrade drops it, which is safe since nothing else
references the column.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4f8d2e6a1c3"
down_revision = "a9e4c7f2b3d6"
branch_labels = None
depends_on = None

TABLE = "va_project_master"
COLUMN = "web_intake_equity_enabled"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column(TABLE, COLUMN)
