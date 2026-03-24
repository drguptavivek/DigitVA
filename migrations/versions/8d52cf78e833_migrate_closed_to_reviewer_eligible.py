"""migrate closed to reviewer_eligible

Revision ID: 8d52cf78e833
Revises: b1c2d3e4f5a6
Create Date: 2026-03-24

The 'closed' workflow state was a legacy compatibility state used before the
reviewer-eligible recode-window path was implemented. All 'closed' rows are
semantically equivalent to 'reviewer_eligible': the coder has finalized, no
active allocation exists, and the case is awaiting the recode window or
reviewer selection. This migration moves all remaining 'closed' rows to
'reviewer_eligible' and writes an audit log entry for each one so the
transition is fully traceable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "8d52cf78e833"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT va_sid FROM va_submission_workflow WHERE workflow_state = 'closed'"
        )
    ).fetchall()

    if not rows:
        return

    now = datetime.now(timezone.utc)

    conn.execute(
        sa.text(
            "UPDATE va_submission_workflow"
            " SET workflow_state = 'reviewer_eligible',"
            "     workflow_reason = 'migrated_from_closed',"
            "     workflow_updated_by_role = 'vasystem'"
            " WHERE workflow_state = 'closed'"
        )
    )

    audit_rows = [
        {
            "va_sid": row.va_sid,
            "va_audit_operation": "u",
            "va_audit_action": "workflow_state_migrated_closed_to_reviewer_eligible",
            "va_audit_byrole": "vasystem",
            "va_audit_createdat": now,
        }
        for row in rows
    ]
    conn.execute(
        sa.text(
            "INSERT INTO va_submissions_auditlog"
            " (va_sid, va_audit_operation, va_audit_action,"
            "  va_audit_byrole, va_audit_createdat)"
            " VALUES"
            " (:va_sid, :va_audit_operation, :va_audit_action,"
            "  :va_audit_byrole, :va_audit_createdat)"
        ),
        audit_rows,
    )


def downgrade() -> None:
    # Not reversible: cannot distinguish rows that were legitimately
    # reviewer_eligible before migration from rows migrated from closed.
    pass
