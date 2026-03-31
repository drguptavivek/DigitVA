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


def _build_legacy_compatible_submission_analytics_mv_sql() -> str:
    """Build a compatibility MV for the pre-rebuild migration chain.

    This migration runs before several later tables and columns exist. The
    later rebuild migration (`b1c2d3e4f5a6`) replaces this with the full view.
    """
    return """
CREATE MATERIALIZED VIEW va_submission_analytics_mv AS
SELECT
    s.va_sid,
    DATE(s.va_submission_date) AS submission_date,
    f.project_id,
    f.site_id,
    w.workflow_state,
    s.va_odk_reviewstate AS odk_review_state,
    s.va_deceased_gender AS sex,
    CASE
        WHEN s.va_deceased_age IS NULL THEN 'unknown'
        WHEN s.va_deceased_age < 15 THEN 'child'
        WHEN s.va_deceased_age < 50 THEN '15_49y'
        WHEN s.va_deceased_age < 65 THEN '50_64y'
        ELSE '65_plus'
    END AS analytics_age_band,
    NULL::text AS final_icd,
    NULL::text AS smartva_cause1_icd
FROM va_submissions s
JOIN va_forms f ON f.form_id = s.va_form_id
LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
WITH DATA
"""


def upgrade():
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
    op.execute(sa.text(_build_legacy_compatible_submission_analytics_mv_sql()))
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
