"""Add source initial-assessment pointer to final assessments.

Revision ID: 7c9d1e2f3a4b
Revises: 678e498f2040
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "7c9d1e2f3a4b"
down_revision = "678e498f2040"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_final_assessments",
        sa.Column("source_initial_assessment_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_final_assessments_source_initial_assessment_id",
        "va_final_assessments",
        ["source_initial_assessment_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_final_assessments_source_initial_assessment_id",
        "va_final_assessments",
        "va_initial_assessments",
        ["source_initial_assessment_id"],
        ["va_iniassess_id"],
        ondelete="SET NULL",
    )

    # Backfill existing rows with a best-effort linkage to the latest initial
    # assessment by the same coder at or before final submission time.
    op.execute(
        """
        UPDATE va_final_assessments
        SET source_initial_assessment_id = (
            SELECT ia.va_iniassess_id
            FROM va_initial_assessments AS ia
            WHERE ia.va_sid = va_final_assessments.va_sid
              AND ia.va_iniassess_by = va_final_assessments.va_finassess_by
              AND ia.va_iniassess_createdat <= va_final_assessments.va_finassess_createdat
            ORDER BY ia.va_iniassess_createdat DESC
            LIMIT 1
        )
        WHERE source_initial_assessment_id IS NULL
        """
    )


def downgrade():
    op.drop_constraint(
        "fk_va_final_assessments_source_initial_assessment_id",
        "va_final_assessments",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_final_assessments_source_initial_assessment_id",
        table_name="va_final_assessments",
    )
    op.drop_column("va_final_assessments", "source_initial_assessment_id")
