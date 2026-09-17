"""core mv: attribute submissions to the form's own project

c6d7e8f9a0b1 derived the core MV's project_id from the site's active
va_project_sites row, joined on site_id alone. A site can be in several
active projects at once (a demo project sharing a real site, a site moved
between projects with both forms retained), so that join fanned out one MV
row per mapping, REFRESH MATERIALIZED VIEW failed on the unique va_sid index,
and moved-site submissions that exist under both forms were double counted.

project_id now comes from va_forms, the form's own (project, site) pair —
the same rule dm_scope_filter applies. Visibility is decided by the scope
filters' comparison against active va_project_sites pairs, not by the MV.

Revision ID: c845df6e64f7
Revises: fe5f6a7b8c9d
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

from app.services.submission_analytics_mv import (
    build_submission_analytics_core_mv_sql,
)

revision = "c845df6e64f7"
down_revision = "fe5f6a7b8c9d"
branch_labels = None
depends_on = None


_INDEXES = (
    ("CREATE UNIQUE INDEX ix_va_submission_analytics_core_mv_va_sid "
     "ON va_submission_analytics_core_mv (va_sid)"),
    ("CREATE INDEX ix_va_submission_analytics_core_mv_submission_date "
     "ON va_submission_analytics_core_mv (submission_date)"),
    ("CREATE INDEX ix_va_submission_analytics_core_mv_project_site "
     "ON va_submission_analytics_core_mv (project_id, site_id)"),
    ("CREATE INDEX ix_va_submission_analytics_core_mv_workflow_state "
     "ON va_submission_analytics_core_mv (workflow_state)"),
    ("CREATE INDEX ix_va_submission_analytics_core_mv_odk_review_state "
     "ON va_submission_analytics_core_mv (odk_review_state)"),
)


def _create_indexes():
    for statement in _INDEXES:
        op.execute(sa.text(statement))


def upgrade():
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_core_mv CASCADE"
    ))
    op.execute(sa.text(build_submission_analytics_core_mv_sql()))
    _create_indexes()


def downgrade():
    # Revert to the c6d7e8f9a0b1 definition (site-only join).
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_core_mv CASCADE"
    ))
    op.execute(sa.text(
        "CREATE MATERIALIZED VIEW va_submission_analytics_core_mv AS "
        "SELECT "
        "  s.va_sid, "
        "  COALESCE(ps.project_id, f.project_id) AS project_id, "
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
        "LEFT JOIN va_project_sites ps "
        "    ON ps.site_id = f.site_id AND ps.project_site_status = 'active' "
        "LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid "
        "WITH DATA"
    ))
    _create_indexes()
