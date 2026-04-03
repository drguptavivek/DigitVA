"""drop_va_data_column

Revision ID: 080779a13b9f
Revises: 79d3e0a77a18
Create Date: 2026-04-03 07:17:51.791778

The demographics materialized view previously read age fields from
va_submissions.va_data. Its definition is updated here to read from
va_submission_payload_versions.payload_data via active_payload_version_id.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = '080779a13b9f'
down_revision = '79d3e0a77a18'
branch_labels = None
depends_on = None

MV_NAME = "va_submission_analytics_demographics_mv"


def upgrade():
    # Drop the MV that depended on va_data, then drop the column.
    # The MV is recreated below with payload_versions as the data source.
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {MV_NAME} CASCADE")
    op.drop_column("va_submissions", "va_data")

    from app.services.submission_analytics_mv import build_submission_analytics_demographics_mv_sql
    op.execute(build_submission_analytics_demographics_mv_sql())


def downgrade():
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {MV_NAME} CASCADE")
    op.add_column(
        "va_submissions",
        sa.Column("va_data", JSONB(), nullable=True),
    )
