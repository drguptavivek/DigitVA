"""widen_va_data_collector_to_128

Revision ID: 7dc60f659cd4
Revises: a8b9c0d1e2f3
Create Date: 2026-03-14 06:48:56.857666

va_data_collector was VARCHAR(32). RJ01 site has long collector names
(e.g. 'RJ01_PHCGudavishnoi_SCMograkalan_ANM_Anjani' = 43 chars). Widen to 128.
"""
from alembic import op
import sqlalchemy as sa


revision = '7dc60f659cd4'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    # Only alter if column is still VARCHAR(32) — safe to re-run.
    conn = op.get_bind()
    col_length = conn.execute(sa.text(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name='va_submissions' AND column_name='va_data_collector'"
    )).scalar()
    if col_length is not None and col_length < 128:
        with op.batch_alter_table('va_submissions', schema=None) as batch_op:
            batch_op.alter_column(
                'va_data_collector',
                existing_type=sa.VARCHAR(length=col_length),
                type_=sa.String(length=128),
                existing_nullable=False,
            )


def downgrade():
    # Only narrow if currently wider — safe to re-run.
    conn = op.get_bind()
    col_length = conn.execute(sa.text(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name='va_submissions' AND column_name='va_data_collector'"
    )).scalar()
    if col_length is not None and col_length > 32:
        with op.batch_alter_table('va_submissions', schema=None) as batch_op:
            batch_op.alter_column(
                'va_data_collector',
                existing_type=sa.String(length=col_length),
                type_=sa.VARCHAR(length=32),
                existing_nullable=False,
            )
