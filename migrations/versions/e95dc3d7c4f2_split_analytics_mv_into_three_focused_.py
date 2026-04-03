"""split analytics mv into three focused mvs

Replace the single wide va_submission_analytics_mv (48 columns) with three
focused materialized views:

  va_submission_analytics_core_mv       — identifiers, timestamps, workflow, sync
  va_submission_analytics_demographics_mv — sex, age band, boolean flags
  va_submission_cod_detail_mv           — COD ICD codes, SmartVA results

Drops 30 unused columns that were never queried by application code.

Revision ID: e95dc3d7c4f2
Revises: cc77dd88ee99
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa

from app.services.submission_analytics_mv import (
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
)

revision = "e95dc3d7c4f2"
down_revision = "cc77dd88ee99"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. Drop the old single wide MV
    # ------------------------------------------------------------------
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_mv CASCADE"
    ))

    # ------------------------------------------------------------------
    # 2. Create MV 1: Core — identifiers, timestamps, workflow, sync
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 3. Create MV 2: Demographics — sex, age band, boolean flags
    # ------------------------------------------------------------------
    op.execute(sa.text(build_submission_analytics_demographics_mv_sql()))

    op.execute(sa.text(
        "CREATE UNIQUE INDEX ix_va_submission_analytics_demographics_mv_va_sid "
        "ON va_submission_analytics_demographics_mv (va_sid)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_demographics_mv_age_band "
        "ON va_submission_analytics_demographics_mv (analytics_age_band)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_analytics_demographics_mv_sex "
        "ON va_submission_analytics_demographics_mv (sex)"
    ))

    # ------------------------------------------------------------------
    # 4. Create MV 3: COD detail — ICD codes, SmartVA results
    # ------------------------------------------------------------------
    op.execute(sa.text(build_submission_cod_detail_mv_sql()))

    op.execute(sa.text(
        "CREATE UNIQUE INDEX ix_va_submission_cod_detail_mv_va_sid "
        "ON va_submission_cod_detail_mv (va_sid)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_cod_detail_mv_final_icd "
        "ON va_submission_cod_detail_mv (final_icd)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_va_submission_cod_detail_mv_smartva_cause1_icd "
        "ON va_submission_cod_detail_mv (smartva_cause1_icd)"
    ))


def downgrade():
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_cod_detail_mv CASCADE"
    ))
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_demographics_mv CASCADE"
    ))
    op.execute(sa.text(
        "DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_core_mv CASCADE"
    ))
