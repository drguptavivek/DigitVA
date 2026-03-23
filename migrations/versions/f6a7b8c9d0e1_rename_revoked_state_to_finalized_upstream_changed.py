"""rename revoked workflow state to finalized_upstream_changed

Revision ID: f6a7b8c9d0e1
Revises: e4f5a6b7c8d9
Create Date: 2026-03-20 20:15:00.000000
"""

from alembic import op


revision = "f6a7b8c9d0e1"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


OLD_STATE = "revoked_va_data_changed"
NEW_STATE = "finalized_upstream_changed"


def upgrade():
    op.execute(
        f"""
        UPDATE va_submission_workflow
        SET workflow_state = '{NEW_STATE}'
        WHERE workflow_state = '{OLD_STATE}'
        """
    )
    op.execute(
        f"""
        UPDATE va_submission_upstream_changes
        SET workflow_state_before = '{NEW_STATE}'
        WHERE workflow_state_before = '{OLD_STATE}'
        """
    )


def downgrade():
    op.execute(
        f"""
        UPDATE va_submission_upstream_changes
        SET workflow_state_before = '{OLD_STATE}'
        WHERE workflow_state_before = '{NEW_STATE}'
        """
    )
    op.execute(
        f"""
        UPDATE va_submission_workflow
        SET workflow_state = '{OLD_STATE}'
        WHERE workflow_state = '{NEW_STATE}'
        """
    )
