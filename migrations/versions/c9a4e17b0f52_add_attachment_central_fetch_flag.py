"""add attachment_central_fetch_enabled to va_project_master

Phase 4a of docs/planning/s3-attachment-plan.md. Additive only: one boolean
per project that decides whether attachment delivery tries ODK Central first
(``true``) or serves the local copy exactly as before (``false``, the default).
Nothing else reads or writes the column, and disabling it returns the project
to the pre-Phase-4 delivery path with no data change.

No index is added: the flag is only ever read by primary key
(``va_project_master.project_id``) on the delivery path.

Downgrade drops the column; no other data is touched.

Revision ID: c9a4e17b0f52
Revises: b7e4c2a91d38
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9a4e17b0f52"
down_revision = "b7e4c2a91d38"
branch_labels = None
depends_on = None


TABLE = "va_project_master"
COLUMN = "attachment_central_fetch_enabled"


def _column_names(bind):
    return {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def upgrade():
    bind = op.get_bind()
    if COLUMN not in _column_names(bind):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade():
    bind = op.get_bind()
    if COLUMN in _column_names(bind):
        op.drop_column(TABLE, COLUMN)
