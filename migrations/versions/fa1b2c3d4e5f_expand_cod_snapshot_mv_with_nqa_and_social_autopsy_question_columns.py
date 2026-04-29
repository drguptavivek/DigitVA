"""expand cod snapshot mv with nqa and social autopsy question columns

Revision ID: fa1b2c3d4e5f
Revises: f8d9e0f1a2b3
Create Date: 2026-04-29 16:45:00.000000

"""

import sqlalchemy as sa
from alembic import op

from app.services.submission_analytics_mv import build_submission_cod_snapshot_mv_sql


# revision identifiers, used by Alembic.
revision = "fa1b2c3d4e5f"
down_revision = "f8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_cod_snapshot_mv CASCADE")
    )
    op.execute(sa.text(build_submission_cod_snapshot_mv_sql()))
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX ix_va_submission_cod_snapshot_mv_va_sid "
            "ON va_submission_cod_snapshot_mv (va_sid)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_snapshot_mv_project_site "
            "ON va_submission_cod_snapshot_mv (project_id, site_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_snapshot_mv_workflow_state "
            "ON va_submission_cod_snapshot_mv (workflow_state)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_snapshot_mv_authoritative_icd "
            "ON va_submission_cod_snapshot_mv (authoritative_icd)"
        )
    )


def downgrade():
    op.execute(
        sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_cod_snapshot_mv CASCADE")
    )
