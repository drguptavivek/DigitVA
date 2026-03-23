"""Add SmartVA failure metadata columns.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-20 10:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_smartva_results",
        sa.Column("va_smartva_outcome", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "va_smartva_results",
        sa.Column("va_smartva_failure_stage", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "va_smartva_results",
        sa.Column("va_smartva_failure_detail", sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE va_smartva_results "
        "SET va_smartva_outcome = 'success' "
        "WHERE va_smartva_outcome IS NULL"
    )
    op.alter_column(
        "va_smartva_results",
        "va_smartva_outcome",
        existing_type=sa.String(length=16),
        nullable=False,
        server_default="success",
    )
    op.create_index(
        "ix_va_smartva_results_va_smartva_outcome",
        "va_smartva_results",
        ["va_smartva_outcome"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_va_smartva_results_va_smartva_outcome",
        table_name="va_smartva_results",
    )
    op.drop_column("va_smartva_results", "va_smartva_failure_detail")
    op.drop_column("va_smartva_results", "va_smartva_failure_stage")
    op.drop_column("va_smartva_results", "va_smartva_outcome")
