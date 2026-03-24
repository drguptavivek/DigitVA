"""rebuild_analytics_mv_add_cod_pending_upstream_review

Adds cod_pending_upstream_review boolean column to the analytics MV.
Cases in finalized_upstream_changed state are now included in coded counts
and flagged with this column so downstream reports can distinguish them.

Revision ID: b1c2d3e4f5a6
Revises: aacf89977029
Create Date: 2026-03-24

"""
import sqlalchemy as sa
from alembic import op

from app.services.submission_analytics_mv import build_submission_analytics_mv_sql

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "aacf89977029"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
    op.execute(sa.text(build_submission_analytics_mv_sql()))

    op.execute(sa.text(
        "CREATE UNIQUE INDEX ix_va_submission_analytics_mv_va_sid "
        "ON va_submission_analytics_mv (va_sid)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_submission_date "
        "ON va_submission_analytics_mv (submission_date)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_project_site "
        "ON va_submission_analytics_mv (project_id, site_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_workflow_state "
        "ON va_submission_analytics_mv (workflow_state)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_odk_review_state "
        "ON va_submission_analytics_mv (odk_review_state)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_age_band "
        "ON va_submission_analytics_mv (analytics_age_band)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_sex "
        "ON va_submission_analytics_mv (sex)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_final_icd "
        "ON va_submission_analytics_mv (final_icd)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_mv_cod_pending "
        "ON va_submission_analytics_mv (cod_pending_upstream_review)"
    ))


def downgrade():
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
