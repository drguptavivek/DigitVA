"""widen_odk_project_id_and_narration_language

Revision ID: 17daf4c488e7
Revises: 7dc60f659cd4
Create Date: 2026-03-14 06:52:22.226328

- va_forms.odk_project_id: VARCHAR(2) → VARCHAR(8)
  Risk: ODK project IDs are integers; anything ≥ 100 (3 digits) would overflow.
- va_submissions.va_narration_language: VARCHAR(16) → VARCHAR(32)
  Future-proofing; current max observed is 9 chars ('malayalam').
"""
from alembic import op
import sqlalchemy as sa


revision = '17daf4c488e7'
down_revision = '7dc60f659cd4'
branch_labels = None
depends_on = None


def _col_length(conn, table, column):
    return conn.execute(sa.text(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar()


def upgrade():
    conn = op.get_bind()

    length = _col_length(conn, 'va_forms', 'odk_project_id')
    if length is not None and length < 8:
        with op.batch_alter_table('va_forms', schema=None) as batch_op:
            batch_op.alter_column(
                'odk_project_id',
                existing_type=sa.VARCHAR(length=length),
                type_=sa.String(length=8),
                existing_nullable=False,
            )

    length = _col_length(conn, 'va_submissions', 'va_narration_language')
    if length is not None and length < 32:
        with op.batch_alter_table('va_submissions', schema=None) as batch_op:
            batch_op.alter_column(
                'va_narration_language',
                existing_type=sa.VARCHAR(length=length),
                type_=sa.String(length=32),
                existing_nullable=False,
            )


def downgrade():
    conn = op.get_bind()

    length = _col_length(conn, 'va_forms', 'odk_project_id')
    if length is not None and length > 2:
        with op.batch_alter_table('va_forms', schema=None) as batch_op:
            batch_op.alter_column(
                'odk_project_id',
                existing_type=sa.String(length=length),
                type_=sa.VARCHAR(length=2),
                existing_nullable=False,
            )

    length = _col_length(conn, 'va_submissions', 'va_narration_language')
    if length is not None and length > 16:
        with op.batch_alter_table('va_submissions', schema=None) as batch_op:
            batch_op.alter_column(
                'va_narration_language',
                existing_type=sa.String(length=length),
                type_=sa.VARCHAR(length=16),
                existing_nullable=False,
            )
