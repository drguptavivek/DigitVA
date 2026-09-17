"""add archive state to va_smartva_form_runs

The SmartVA run archival phase of docs/planning/s3-attachment-plan.md. A run
directory is a local working area the SmartVA CLI needs while it runs; once its
likelihood rows are in ``va_smartva_run_outputs`` nothing in the app reads it
again. With ``ATTACHMENT_STORE=s3`` the directory is copied to the DigitVA
bucket under ``smartva_runs/<project_id>/<form_id>/<form_run_id>/`` and the
local copy is removed, so the VM keeps only what a running job needs.

Additive only. The six columns below record where a run's directory now lives
and what the archive contained; ``disk_path`` is untouched and keeps its
meaning (it becomes NULL only when a *verified* archive lets the local copy go).
Every existing row keeps its meaning: the server default backfills ``local``,
which is exactly what those rows are — directories on this VM. No file, object
or other column is touched, and no row is deleted or rewritten.

A plain index on ``archive_state`` is added because the backlog CLI, the Celery
sweep and the admin panel all select or group by it.

Downgrade drops the six columns and the index; the directories and the archived
objects are untouched, so a downgrade loses only the bookkeeping.

Revision ID: d3b8f1e40a72
Revises: a4f1c07b62d9
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d3b8f1e40a72"
down_revision = "a4f1c07b62d9"
branch_labels = None
depends_on = None


TABLE = "va_smartva_form_runs"
INDEX = "ix_va_smartva_form_runs_archive_state"

# Built fresh per call: a Column object may only be attached to one table.
def _columns():
    return (
        sa.Column(
            "archive_state",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'local'"),
        ),
        sa.Column("archive_key_prefix", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_error_code", sa.String(length=32), nullable=True),
        sa.Column("archive_file_count", sa.Integer(), nullable=True),
        sa.Column("archive_bytes", sa.BigInteger(), nullable=True),
    )


def _column_names(bind):
    return {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def _index_names(bind):
    return {i["name"] for i in sa.inspect(bind).get_indexes(TABLE)}


def upgrade():
    bind = op.get_bind()
    existing = _column_names(bind)
    for column in _columns():
        if column.name not in existing:
            op.add_column(TABLE, column)
    if INDEX not in _index_names(bind):
        op.create_index(INDEX, TABLE, ["archive_state"])


def downgrade():
    bind = op.get_bind()
    if INDEX in _index_names(bind):
        op.drop_index(INDEX, table_name=TABLE)
    existing = _column_names(bind)
    for column in reversed(_columns()):
        if column.name in existing:
            op.drop_column(TABLE, column.name)
