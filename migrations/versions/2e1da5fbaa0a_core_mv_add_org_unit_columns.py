"""core mv: add org_unit_id, org_unit_code, org_unit_path

Phase 5 of the health-system organization model (reporting dimensions):
docs/current-state/health-system-organization-model.md. Unit-level
reporting needs the organization unit on each submission row without a
per-query join back to mas_org_unit, and a subtree rollup ("this district's
count includes every PHC beneath it") needs the unit's ltree path so the
rollup is one indexed `<@` query rather than a walk per unit.

org_unit_id and org_unit_code are NULL for a project with no organization
tree, and for an unrouted submission of one that has a tree — exactly like
va_submissions.org_unit_id itself. No existing column changes name, type or
meaning.

Revision ID: 2e1da5fbaa0a
Revises: f7b2d4e6a8c9
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

from app.services.submission_analytics_mv import build_submission_analytics_core_mv_sql

revision = "2e1da5fbaa0a"
down_revision = "f7b2d4e6a8c9"
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
    ("CREATE INDEX ix_va_submission_analytics_core_mv_odk_missing "
     "ON va_submission_analytics_core_mv (odk_missing, project_id, site_id)"),
)

# The unit id is used for direct equality lookups; the path is what makes a
# subtree rollup ("this unit and everything beneath it") a single indexed
# `<@` query instead of a per-unit walk — the same pattern mas_org_unit.path
# itself uses (ix_mas_org_unit_path).
_ORG_UNIT_INDEXES = (
    ("CREATE INDEX ix_va_submission_analytics_core_mv_org_unit_id "
     "ON va_submission_analytics_core_mv (org_unit_id)"),
    ("CREATE INDEX ix_va_submission_analytics_core_mv_org_unit_path "
     "ON va_submission_analytics_core_mv USING GIST (org_unit_path)"),
)


def _create_indexes():
    for statement in _INDEXES:
        op.execute(sa.text(statement))
    for statement in _ORG_UNIT_INDEXES:
        op.execute(sa.text(statement))


def upgrade():
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_core_mv CASCADE"
    ))
    # include_org_unit=True: this is the migration that introduces the org
    # unit columns. Every earlier migration calling this same function keeps
    # the default (False) and is therefore unaffected by this change — see
    # the module docstring in app/services/submission_analytics_mv.py.
    op.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
    _create_indexes()


def downgrade():
    # Revert to the d3f1a7c92b64 definition (no org unit columns).
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
        "  (s.va_sync_issue_code IS NOT DISTINCT FROM 'missing_in_odk') AS odk_missing, "
        "  (w.workflow_state = 'finalized_upstream_changed') AS cod_pending_upstream_review "
        "FROM va_submissions s "
        "JOIN va_forms f ON f.form_id = s.va_form_id "
        "LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid "
        "WITH DATA"
    ))
    for statement in _INDEXES:
        op.execute(sa.text(statement))
