"""add store_state to va_submission_attachments

The S3 store phase of docs/planning/s3-attachment-plan.md. Additive only: one
column recording which store holds a row's object — ``local`` (a file under
APP_DATA/<form_id>/media/, the historical and default state), ``s3`` (an object
in the DigitVA bucket, with ``local_path`` NULL), or ``absent`` (not stored
anywhere yet).

Every existing row keeps its meaning: the server default backfills ``local``,
which is exactly what those rows are. No file, object, or other column is
touched, and no row is deleted or rewritten.

A plain index is added because the cutover tool and the integrity check both
select rows by store, and the readiness read reports the column.

Downgrade drops the column and its index; no data outside the column is
affected.

Revision ID: a4f1c07b62d9
Revises: c9a4e17b0f52
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a4f1c07b62d9"
down_revision = "c9a4e17b0f52"
branch_labels = None
depends_on = None


TABLE = "va_submission_attachments"
COLUMN = "store_state"
INDEX = "ix_va_submission_attachments_store_state"


def _column_names(bind):
    return {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def _index_names(bind):
    return {i["name"] for i in sa.inspect(bind).get_indexes(TABLE)}


def upgrade():
    bind = op.get_bind()
    if COLUMN not in _column_names(bind):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'local'"),
            ),
        )
    if INDEX not in _index_names(bind):
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade():
    bind = op.get_bind()
    if INDEX in _index_names(bind):
        op.drop_index(INDEX, table_name=TABLE)
    if COLUMN in _column_names(bind):
        op.drop_column(TABLE, COLUMN)
