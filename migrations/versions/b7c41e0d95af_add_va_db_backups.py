"""add va_db_backups

Item 3 of the queued phases in docs/planning/s3-attachment-plan.md: the nightly
``pg_dump`` goes to the DigitVA bucket under ``db-backups/`` and the VM keeps no
dump history. This table is the history — one row per dump, with where it went,
how big it was and its sha256, so an operator can see the schedule working and a
restore can verify the bytes it downloaded.

Purely additive: a new operational table beside ``va_sync_runs``, whose shape
and naming it follows. Nothing existing is read, rewritten or dropped, so the
upgrade is safe to run against a live database and the downgrade loses only this
bookkeeping — never a dump, which lives in the bucket.

Two indexes because the admin panel and the CLI list the most recent backups
(``started_at DESC``) and the overview counts by ``status``.

Revision ID: b7c41e0d95af
Revises: d3b8f1e40a72
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c41e0d95af"
down_revision = "d3b8f1e40a72"
branch_labels = None
depends_on = None


TABLE = "va_db_backups"
INDEX_STARTED_AT = "ix_va_db_backups_started_at"
INDEX_STATUS = "ix_va_db_backups_status"


def _table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind):
    return {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}


def upgrade():
    bind = op.get_bind()
    if TABLE not in _table_names(bind):
        op.create_table(
            TABLE,
            sa.Column("backup_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("triggered_by", sa.String(length=16), nullable=False),
            sa.Column("triggered_user_id", sa.Uuid(as_uuid=True), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("store", sa.String(length=8), nullable=False),
            sa.Column("object_key", sa.Text(), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("sha256", sa.String(length=64), nullable=True),
            sa.Column("error_code", sa.String(length=32), nullable=True),
            sa.Column("pruned_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("backup_id", name="pk_va_db_backups"),
            sa.ForeignKeyConstraint(
                ["triggered_user_id"],
                ["va_users.user_id"],
                name="fk_va_db_backups_triggered_user_id",
            ),
        )

    existing = _index_names(bind)
    if INDEX_STARTED_AT not in existing:
        op.create_index(
            INDEX_STARTED_AT, TABLE, [sa.text("started_at DESC")]
        )
    if INDEX_STATUS not in existing:
        op.create_index(INDEX_STATUS, TABLE, ["status"])


def downgrade():
    bind = op.get_bind()
    if TABLE not in _table_names(bind):
        return
    existing = _index_names(bind)
    if INDEX_STATUS in existing:
        op.drop_index(INDEX_STATUS, table_name=TABLE)
    if INDEX_STARTED_AT in existing:
        op.drop_index(INDEX_STARTED_AT, table_name=TABLE)
    op.drop_table(TABLE)
