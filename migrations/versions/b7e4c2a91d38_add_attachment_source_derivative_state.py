"""add source/derivative/local-fallback state to va_submission_attachments

Phase 2 of docs/planning/s3-attachment-plan.md. Additive only: existing rows
and the meaning of ``local_path``/``storage_name`` are unchanged, and nothing
reads the new columns for a decision yet. They carry the readiness state the
attachment service needs in Phase 4/5 so presence stops being a question about
the local filesystem.

Vocabularies live in ``app/services/attachment_service.py``.

Backfill (set-based, idempotent — each statement only touches rows still at the
column default, so a rerun never overwrites state sync has since written):

* ``source_state``  'listed' when the attachment was listed by ODK
  (``exists_on_odk``), 'missing' otherwise. 'available' requires an observed
  content response, which no existing row can prove.
* ``derivative_*``  AMR rows only (``filename`` ends ``.amr`` and the blob was
  stored as ``.mp3``). The local file cannot be stat-ed during a migration, so
  a row with no ``local_path`` is 'pending' and any other is 'ready', with the
  stored ETag kept as the validator the MP3 was built from.
* ``local_fallback_state``  'retained' for attachments of submissions retired
  from ODK (docs/policy/odk-retired-submissions.md): Central has purged the
  source, so the local copy is archival and is never quarantined.

Downgrade drops the indexes and the columns; no other data is touched.

Revision ID: b7e4c2a91d38
Revises: d3f1a7c92b64
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7e4c2a91d38"
down_revision = "d3f1a7c92b64"
branch_labels = None
depends_on = None


TABLE = "va_submission_attachments"


def _new_columns():
    """Fresh Column objects; an Alembic op consumes the object it is given.

    Every NOT NULL column carries a server_default, so each ADD COLUMN is a
    single fast statement and PostgreSQL does not rewrite the table.
    """
    return (
        sa.Column("source_state", sa.String(length=16), nullable=False,
                  server_default=sa.text("'unknown'")),
        sa.Column("source_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_error_code", sa.String(length=32), nullable=True),
        sa.Column("source_mime_type", sa.String(length=64), nullable=True),
        sa.Column("derivative_state", sa.String(length=16), nullable=True),
        sa.Column("derivative_mime_type", sa.String(length=64), nullable=True),
        sa.Column("derivative_source_validator", sa.String(length=128), nullable=True),
        sa.Column("derivative_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("derivative_error_code", sa.String(length=32), nullable=True),
        sa.Column("local_fallback_state", sa.String(length=16), nullable=False,
                  server_default=sa.text("'present'")),
    )


_SOURCE_STATE_INDEX = "ix_va_submission_attachments_source_state"
_DERIVATIVE_STATE_INDEX = "ix_va_submission_attachments_derivative_state"

MISSING_IN_ODK = "missing_in_odk"


def _existing(inspector, kind):
    if kind == "columns":
        return {c["name"] for c in inspector.get_columns(TABLE)}
    return {i["name"] for i in inspector.get_indexes(TABLE)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    present_columns = _existing(inspector, "columns")
    for column in _new_columns():
        if column.name not in present_columns:
            op.add_column(TABLE, column)

    present_indexes = _existing(sa.inspect(bind), "indexes")
    if _SOURCE_STATE_INDEX not in present_indexes:
        op.create_index(_SOURCE_STATE_INDEX, TABLE, ["source_state"], unique=False)
    if _DERIVATIVE_STATE_INDEX not in present_indexes:
        op.create_index(
            _DERIVATIVE_STATE_INDEX,
            TABLE,
            ["derivative_state"],
            unique=False,
            postgresql_where=sa.text("derivative_state IS NOT NULL"),
        )

    op.execute(
        sa.text(
            f"UPDATE {TABLE} SET source_state = CASE WHEN exists_on_odk "
            "THEN 'listed' ELSE 'missing' END WHERE source_state = 'unknown'"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE {TABLE} SET "
            "derivative_state = CASE WHEN local_path IS NULL "
            "THEN 'pending' ELSE 'ready' END, "
            "derivative_mime_type = 'audio/mpeg', "
            "derivative_source_validator = etag "
            "WHERE derivative_state IS NULL "
            "AND filename ILIKE '%.amr' "
            "AND storage_name LIKE '%.mp3'"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE {TABLE} AS a SET local_fallback_state = 'retained' "
            "FROM va_submissions AS s "
            "WHERE s.va_sid = a.va_sid "
            "AND s.va_sync_issue_code = :missing_in_odk "
            "AND a.local_fallback_state = 'present'"
        ).bindparams(missing_in_odk=MISSING_IN_ODK)
    )


def downgrade():
    bind = op.get_bind()
    present_indexes = _existing(sa.inspect(bind), "indexes")
    for index_name in (_DERIVATIVE_STATE_INDEX, _SOURCE_STATE_INDEX):
        if index_name in present_indexes:
            op.drop_index(index_name, table_name=TABLE)

    present_columns = _existing(sa.inspect(bind), "columns")
    for column in reversed(_new_columns()):
        if column.name in present_columns:
            op.drop_column(TABLE, column.name)
