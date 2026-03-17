"""add submission analytics materialized view

Revision ID: 8b9c0d1e2f34
Revises: 6a7b8c9d0e1f
Create Date: 2026-03-18 23:10:00.000000

"""

from alembic import op
import sqlalchemy as sa

from app.services.submission_analytics_mv import build_submission_analytics_mv_sql


# revision identifiers, used by Alembic.
revision = "8b9c0d1e2f34"
down_revision = "6a7b8c9d0e1f"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
    op.execute(sa.text(build_submission_analytics_mv_sql()))
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX ix_va_submission_analytics_mv_va_sid "
            "ON va_submission_analytics_mv (va_sid)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_submission_date "
            "ON va_submission_analytics_mv (submission_date)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_project_site "
            "ON va_submission_analytics_mv (project_id, site_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_workflow_state "
            "ON va_submission_analytics_mv (workflow_state)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_odk_review_state "
            "ON va_submission_analytics_mv (odk_review_state)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_age_band "
            "ON va_submission_analytics_mv (analytics_age_band)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_sex "
            "ON va_submission_analytics_mv (sex)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_final_icd "
            "ON va_submission_analytics_mv (final_icd)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_analytics_mv_smartva_cause1_icd "
            "ON va_submission_analytics_mv (smartva_cause1_icd)"
        )
    )


def downgrade():
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
