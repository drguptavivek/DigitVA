"""Add web_intake_medical_records_enabled to va_project_master.

Revision ID: e1b6c9a3d7f4
Revises: a7d4f1c9b0e6
Create Date: 2026-09-19 19:00:00.000000

``medical_records`` becomes a named extension in ``enabled_extensions``
(decided 2026-09-19, docs/policy/va-web-form-options.md): the ``md_available``
/ ``md_count`` / ``md_im1``..``md_im30`` fields move out of ``digitva_core``
into their own layer, mirroring how ``death_summary`` already has its own
project switch. The default is ``true`` because every existing project's
questionnaire already carries the medical-record fields today -- turning the
column on preserves current behaviour, and an administrator opts a project
out rather than every project having to opt in.

Purely additive: one new column, no existing column touched, no data
rewritten. The downgrade drops it, which is safe since nothing else
references the column.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e1b6c9a3d7f4"
down_revision = "a7d4f1c9b0e6"
branch_labels = None
depends_on = None

TABLE = "va_project_master"
COLUMN = "web_intake_medical_records_enabled"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade():
    op.drop_column(TABLE, COLUMN)
