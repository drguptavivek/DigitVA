"""add WHO ICD-11 provenance to assessment rows

Revision ID: d9e0f1a2b3c4
Revises: b7e2a9c4d6f1
Create Date: 2026-09-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d9e0f1a2b3c4"
down_revision = "b7e2a9c4d6f1"
branch_labels = None
depends_on = None


def upgrade():
    for table in (
        "va_initial_assessments",
        "va_final_assessments",
        "va_reviewer_initial_assessments",
        "va_reviewer_final_assessments",
    ):
        op.add_column(
            table,
            sa.Column("icd11_provenance", postgresql.JSONB(), nullable=True),
        )


def downgrade():
    for table in (
        "va_reviewer_final_assessments",
        "va_reviewer_initial_assessments",
        "va_final_assessments",
        "va_initial_assessments",
    ):
        op.drop_column(table, "icd11_provenance")
