"""add precomputed metadata fields to va_submission_payload_versions

Eliminates 8 JSONB field extractions per row in the backfill-stats aggregation.
Previously the query evaluated payload_data->>'FormVersion' IS NOT NULL (×6) and
CAST(nullif(payload_data->>'AttachmentsExpected','') AS INTEGER) for every row at
query time.  These two columns make that a simple boolean/integer column read.

  has_required_metadata  — True iff all 6 sync-completeness fields are present
                           in payload_data (FormVersion, DeviceID, SubmitterID,
                           instanceID, AttachmentsExpected, AttachmentsPresent).

  attachments_expected   — integer value of payload_data->>'AttachmentsExpected',
                           NULL when absent or non-numeric.

Both columns are set at insert time by _derive_payload_metadata() in
submission_payload_version_service.py and backfilled here for existing rows.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa

revision = "a4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None

_REQUIRED_METADATA_KEYS = [
    "FormVersion",
    "DeviceID",
    "SubmitterID",
    "instanceID",
    "AttachmentsExpected",
    "AttachmentsPresent",
]


def upgrade():
    op.add_column(
        "va_submission_payload_versions",
        sa.Column("has_required_metadata", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "va_submission_payload_versions",
        sa.Column("attachments_expected", sa.Integer(), nullable=True),
    )

    # Backfill from existing payload_data JSONB
    not_null_checks = " AND ".join(
        f"(payload_data ->> '{k}') IS NOT NULL" for k in _REQUIRED_METADATA_KEYS
    )
    op.execute(f"""
        UPDATE va_submission_payload_versions
        SET
            has_required_metadata = ({not_null_checks}),
            attachments_expected   = CAST(
                nullif((payload_data ->> 'AttachmentsExpected'), '')
                AS INTEGER
            )
    """)

    # Make non-nullable now that backfill is done
    op.alter_column(
        "va_submission_payload_versions",
        "has_required_metadata",
        nullable=False,
        server_default=sa.false(),
    )


def downgrade():
    op.drop_column("va_submission_payload_versions", "attachments_expected")
    op.drop_column("va_submission_payload_versions", "has_required_metadata")
