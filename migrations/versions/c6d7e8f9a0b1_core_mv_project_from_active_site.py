"""core mv: derive project_id from active site mapping

The core analytics MV previously took project_id from va_forms.project_id.
When a site moves between projects (e.g. NC02 from ICMR01 to TELE01), the
form keeps its old project_id but va_project_sites is updated.  This left
submissions invisible to both the old project (site deactivated) and the new
project (MV still had the old project_id).

Now project_id is derived from va_project_sites (active entry) with a
COALESCE fallback to va_forms.project_id for sites with no active mapping.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa

from app.services.submission_analytics_mv import (
    build_submission_analytics_core_mv_sql,
)

revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade():
    # Drop core MV + indexes, recreate with new definition
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_core_mv CASCADE"
    ))
    op.execute(sa.text(build_submission_analytics_core_mv_sql()))

    op.execute(sa.text(
        "CREATE UNIQUE INDEX ix_va_submission_analytics_core_mv_va_sid "
        "ON va_submission_analytics_core_mv (va_sid)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_submission_date "
        "ON va_submission_analytics_core_mv (submission_date)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_project_site "
        "ON va_submission_analytics_core_mv (project_id, site_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_workflow_state "
        "ON va_submission_analytics_core_mv (workflow_state)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_odk_review_state "
        "ON va_submission_analytics_core_mv (odk_review_state)"
    ))


def downgrade():
    # Revert to the old definition (project_id from va_forms)
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_core_mv CASCADE"
    ))
    op.execute(sa.text(
        "CREATE MATERIALIZED VIEW va_submission_analytics_core_mv AS "
        "SELECT "
        "  s.va_sid, "
        "  f.project_id, "
        "  f.site_id, "
        "  s.va_submission_date AS submission_at, "
        "  DATE(s.va_submission_date) AS submission_date, "
        "  DATE_TRUNC('week', s.va_submission_date)::date AS submission_week_start, "
        "  DATE_TRUNC('month', s.va_submission_date)::date AS submission_month_start, "
        "  w.workflow_state, "
        "  s.va_odk_reviewstate AS odk_review_state, "
        "  s.va_sync_issue_code AS odk_sync_issue_code, "
        "  (s.va_sync_issue_code IS NOT NULL) AS has_sync_issue, "
        "  (w.workflow_state = 'finalized_upstream_changed') AS cod_pending_upstream_review "
        "FROM va_submissions s "
        "JOIN va_forms f ON f.form_id = s.va_form_id "
        "LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid "
        "WITH DATA"
    ))

    op.execute(sa.text(
        "CREATE UNIQUE INDEX ix_va_submission_analytics_core_mv_va_sid "
        "ON va_submission_analytics_core_mv (va_sid)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_submission_date "
        "ON va_submission_analytics_core_mv (submission_date)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_project_site "
        "ON va_submission_analytics_core_mv (project_id, site_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_workflow_state "
        "ON va_submission_analytics_core_mv (workflow_state)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_core_mv_odk_review_state "
        "ON va_submission_analytics_core_mv (odk_review_state)"
    ))
