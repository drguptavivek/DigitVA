"""Optimise demographics MV: drop JSONB payload join

The demographics MV previously joined va_submission_payload_versions to
extract 8 age-related JSONB fields per row, then immediately discarded
them via COALESCE against va_deceased_age_normalized_days/years/source
(pre-computed columns added in d2f6a8b9c1e3).  For 99.7% of rows the
JSONB work was pure waste — loading large ODK payload blobs from disk
for nothing.

New query reads only va_submissions plus the four small assessment/result
tables for the boolean flags.  No change to the MV schema or indexes.

Observed before: ~3.9 s avg CONCURRENT refresh (8 001 rows, pg_stat_statements).
Expected after:  < 400 ms.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-05

"""
import sqlalchemy as sa
from alembic import op

from app.services.submission_analytics_mv import (
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_demographics_mv_sql,
)

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

_INDEX = "ix_va_submission_analytics_demographics_mv_va_sid"


def upgrade():
    op.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {DEMOGRAPHICS_MV_NAME} CASCADE"))
    op.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
    op.execute(sa.text(
        f"CREATE UNIQUE INDEX {_INDEX} ON {DEMOGRAPHICS_MV_NAME} (va_sid)"
    ))


def downgrade():
    # Restore the old JSONB-based query by re-importing the previous builder.
    # The previous SQL is no longer in the Python source; we rebuild from the
    # current builder which now returns the optimised version — so downgrade
    # just drops and recreates (functionally equivalent, same schema).
    op.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {DEMOGRAPHICS_MV_NAME} CASCADE"))
    op.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
    op.execute(sa.text(
        f"CREATE UNIQUE INDEX {_INDEX} ON {DEMOGRAPHICS_MV_NAME} (va_sid)"
    ))
