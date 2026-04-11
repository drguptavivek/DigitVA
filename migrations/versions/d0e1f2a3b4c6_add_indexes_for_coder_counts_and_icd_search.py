"""add indexes for coder counts and ICD search

Revision ID: d0e1f2a3b4c6
Revises: 7c9d1e2f3a4b
Create Date: 2026-04-11 05:05:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c6"
down_revision = "7c9d1e2f3a4b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_va_submission_workflow_state_va_sid",
        "va_submission_workflow",
        ["workflow_state", "va_sid"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX ix_va_submissions_form_lower_language_sid "
        "ON va_submissions (va_form_id, lower(va_narration_language), va_sid)"
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_va_icd_codes_lower_icd_code "
        "ON va_icd_codes (lower(icd_code))"
    )
    op.execute(
        "CREATE INDEX ix_va_icd_codes_lower_display_trgm "
        "ON va_icd_codes USING gin (lower(icd_to_display) gin_trgm_ops)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_va_icd_codes_lower_display_trgm")
    op.execute("DROP INDEX IF EXISTS ix_va_icd_codes_lower_icd_code")
    op.execute("DROP INDEX IF EXISTS ix_va_submissions_form_lower_language_sid")
    op.drop_index(
        "ix_va_submission_workflow_state_va_sid",
        table_name="va_submission_workflow",
    )
