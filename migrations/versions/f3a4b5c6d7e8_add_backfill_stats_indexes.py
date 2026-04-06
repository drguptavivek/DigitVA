"""add indexes for admin sync backfill-stats query

Two targeted indexes that eliminate full-table scans in
GET /api/sync/backfill-stats:

  1. Partial index on va_submission_attachments(va_sid) WHERE exists_on_odk
     — the attachment subquery groups by va_sid after filtering to
       exists_on_odk IS TRUE; without this the planner does a seq-scan +
       hash-aggregate over the whole table.

  2. Composite index on va_smartva_results(va_sid, va_smartva_status)
     — allows an index-only scan for the has-active-smartva subquery
       (SELECT max(CASE WHEN status='active' ...) GROUP BY va_sid).

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-06
"""
from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    # Partial index: only the rows the attachment subquery cares about
    op.create_index(
        "ix_va_submission_attachments_sid_odk",
        "va_submission_attachments",
        ["va_sid"],
        postgresql_where="exists_on_odk IS TRUE",
    )

    # Composite covering index for the SmartVA has-active check
    op.create_index(
        "ix_va_smartva_results_sid_status_covering",
        "va_smartva_results",
        ["va_sid", "va_smartva_status"],
    )


def downgrade():
    op.drop_index("ix_va_smartva_results_sid_status_covering", table_name="va_smartva_results")
    op.drop_index("ix_va_submission_attachments_sid_odk", table_name="va_submission_attachments")
