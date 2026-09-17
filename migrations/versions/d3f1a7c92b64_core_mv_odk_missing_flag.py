"""core mv: add odk_missing so consumers can exclude retired submissions

Submissions whose va_sync_issue_code is 'missing_in_odk' are retired from ODK
(docs/policy/odk-retired-submissions.md): kept with their history, but not
counted by default. The rows stay in the MV so the explicit "Missing in ODK"
count can still find them; the new boolean lets every consumer filter them out
with an indexed column instead of re-deriving the comparison.

Revision ID: d3f1a7c92b64
Revises: c845df6e64f7
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

from app.services.submission_analytics_mv import (
    build_submission_analytics_core_mv_sql,
)

revision = "d3f1a7c92b64"
down_revision = "c845df6e64f7"
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

# Every scoped read now filters on odk_missing, so it is indexed alongside the
# scope columns it is always combined with.
_ODK_MISSING_INDEX = (
    "CREATE INDEX ix_va_submission_analytics_core_mv_odk_missing "
    "ON va_submission_analytics_core_mv (odk_missing, project_id, site_id)"
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
    op.execute(sa.text(_ODK_MISSING_INDEX))


def downgrade():
    # Revert to the c845df6e64f7 definition (no odk_missing column).
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
    _create_indexes()
