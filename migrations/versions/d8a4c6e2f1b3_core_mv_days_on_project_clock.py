"""core mv: submission_date, week and month starts on the project clock

Policy: docs/policy/kpis.md ("Days follow the project clock") and
docs/policy/project-clock-and-gates.md ("Project clock"); bead digitva-apee.
The core MV took a submission's day, week and month in UTC. They are now taken
in the timezone of the submission's project (``va_project_master.timezone``,
default Asia/Kolkata; ``va_submission_date`` is naive UTC), so every reader of
``submission_date`` (the date filters, the analytics day/week/month series, the
AI cube's month, the COD bucket report) follows the project clock with the
column still indexed. The master join is LEFT (``va_forms.project_id`` points
at ``va_research_projects``), so the view keeps one row per submission. A
project timezone edit shows after the next refresh.

The SQL is inlined (tests/migrations/test_no_app_imports_in_migrations.py).
Downgrade restores the 2e1da5fbaa0a definition (UTC days). No data is lost:
the view is rebuilt from va_submissions either way.

Revision ID: d8a4c6e2f1b3
Revises: c3f9a2d6e8b4
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision = "d8a4c6e2f1b3"
down_revision = "c3f9a2d6e8b4"
branch_labels = None
depends_on = None


_INDEXES = (
    "CREATE UNIQUE INDEX ix_va_submission_analytics_core_mv_va_sid "
    "ON va_submission_analytics_core_mv (va_sid)",
    "CREATE INDEX ix_va_submission_analytics_core_mv_submission_date "
    "ON va_submission_analytics_core_mv (submission_date)",
    "CREATE INDEX ix_va_submission_analytics_core_mv_project_site "
    "ON va_submission_analytics_core_mv (project_id, site_id)",
    "CREATE INDEX ix_va_submission_analytics_core_mv_workflow_state "
    "ON va_submission_analytics_core_mv (workflow_state)",
    "CREATE INDEX ix_va_submission_analytics_core_mv_odk_review_state "
    "ON va_submission_analytics_core_mv (odk_review_state)",
    "CREATE INDEX ix_va_submission_analytics_core_mv_odk_missing "
    "ON va_submission_analytics_core_mv (odk_missing, project_id, site_id)",
    "CREATE INDEX ix_va_submission_analytics_core_mv_org_unit_id "
    "ON va_submission_analytics_core_mv (org_unit_id)",
    "CREATE INDEX ix_va_submission_analytics_core_mv_org_unit_path "
    "ON va_submission_analytics_core_mv USING GIST (org_unit_path)",
)


def _core_mv_sql(local_sql: str, clock_join: str) -> str:
    return f"""
CREATE MATERIALIZED VIEW va_submission_analytics_core_mv AS
SELECT
    s.va_sid,
    f.project_id,
    f.site_id,
    s.va_submission_date AS submission_at,
    DATE({local_sql}) AS submission_date,
    DATE_TRUNC('week', {local_sql})::date AS submission_week_start,
    DATE_TRUNC('month', {local_sql})::date AS submission_month_start,
    w.workflow_state,
    s.va_odk_reviewstate AS odk_review_state,
    s.va_sync_issue_code AS odk_sync_issue_code,
    (s.va_sync_issue_code IS NOT NULL) AS has_sync_issue,
    (s.va_sync_issue_code IS NOT DISTINCT FROM 'missing_in_odk') AS odk_missing,
    (w.workflow_state = 'finalized_upstream_changed') AS cod_pending_upstream_review,
    s.org_unit_id,
    ou.unit_code AS org_unit_code,
    ou.path AS org_unit_path
FROM va_submissions s
JOIN va_forms f ON f.form_id = s.va_form_id{clock_join}
LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
LEFT JOIN mas_org_unit ou ON ou.org_unit_id = s.org_unit_id
WITH DATA
"""


def _rebuild(local_sql: str, clock_join: str = "") -> None:
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_core_mv CASCADE"))
    op.execute(sa.text(_core_mv_sql(local_sql, clock_join)))
    for statement in _INDEXES:
        op.execute(sa.text(statement))


def upgrade():
    _rebuild(
        "timezone(COALESCE(pm.timezone, 'Asia/Kolkata'), timezone('UTC', s.va_submission_date))",
        "\nLEFT JOIN va_project_master pm ON pm.project_id = f.project_id",
    )


def downgrade():
    _rebuild("s.va_submission_date")
