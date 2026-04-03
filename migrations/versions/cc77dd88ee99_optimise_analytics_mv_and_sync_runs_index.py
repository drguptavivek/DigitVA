"""optimise_analytics_mv_and_sync_runs_index

Replace LATERAL correlated subqueries in the analytics MV with pre-aggregated
DISTINCT ON joins. Each of the four LATERAL clauses previously ran one correlated
lookup per outer row (8 000 rows × 7 lookups ≈ 56 000 round-trips). The rewrite
executes a fixed number of table scans regardless of row count, cutting refresh
time from ~68 s (concurrent) / ~36 s (non-concurrent) to under 5 s.

Also adds a composite index on va_sync_runs(status, started_at DESC) to cover
the status-filtered, time-ordered queries that were causing full table scans.

Revision ID: cc77dd88ee99
Revises: aa12bb34cc56
Create Date: 2026-04-02

"""
import sqlalchemy as sa
from alembic import op

revision = "cc77dd88ee99"
down_revision = "aa12bb34cc56"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. Rebuild the analytics MV with optimised query
    # ------------------------------------------------------------------
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
    op.execute(sa.text(build_submission_analytics_mv_sql()))

    # Recreate all MV indexes
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

    # ------------------------------------------------------------------
    # 2. Composite index on va_sync_runs(status, started_at DESC)
    #    Covers: WHERE status = ? ORDER BY started_at DESC LIMIT n
    #    Replaces full table scans caused by status-only filtering.
    # ------------------------------------------------------------------
    op.execute(sa.text(
        "CREATE INDEX ix_va_sync_runs_status_started_at "
        "ON va_sync_runs (status, started_at DESC)"
    ))


def downgrade():
    op.execute(sa.text("DROP INDEX IF EXISTS ix_va_sync_runs_status_started_at"))
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"))
