"""Fix demographics MV missing unique index

Migration a1b3c5d7e9f0 dropped and recreated va_submission_analytics_demographics_mv
but omitted the unique index on va_sid, breaking CONCURRENT refresh.  This migration
recreates the unique index (and the two non-unique indexes) if they are missing.

Revision ID: c8d9e0f1a2b3
Revises: add_nqa_cannot_grade
Create Date: 2026-04-07

"""
from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "add_nqa_cannot_grade"
branch_labels = None
depends_on = None

MV = "va_submission_analytics_demographics_mv"

INDEXES = [
    (
        "ix_va_submission_analytics_demographics_mv_va_sid",
        f"CREATE UNIQUE INDEX {{}} ON {MV} (va_sid)",
    ),
    (
        "ix_va_submission_analytics_demographics_mv_age_band",
        f"CREATE INDEX {{}} ON {MV} (analytics_age_band)",
    ),
    (
        "ix_va_submission_analytics_demographics_mv_sex",
        f"CREATE INDEX {{}} ON {MV} (sex)",
    ),
]


def upgrade():
    for idx_name, create_sql in INDEXES:
        op.execute(
            f"DO $func$ BEGIN "
            f"  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = '{idx_name}') THEN "
            f"    EXECUTE '{create_sql.format(idx_name)}'; "
            f"  END IF; "
            f"END $func$"
        )


def downgrade():
    # No-op: removing indexes would break CONCURRENT refresh again.
    pass
