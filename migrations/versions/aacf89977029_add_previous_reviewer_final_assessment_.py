"""add_previous_reviewer_final_assessment_id_to_upstream_changes

Revision ID: aacf89977029
Revises: 5e6f7a8b9c0d
Create Date: 2026-03-24 06:35:48.445722

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'aacf89977029'
down_revision = '5e6f7a8b9c0d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('va_submission_upstream_changes', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('previous_reviewer_final_assessment_id', sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_va_upstream_changes_prev_reviewer_final',
            'va_reviewer_final_assessments',
            ['previous_reviewer_final_assessment_id'],
            ['va_rfinassess_id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('va_submission_upstream_changes', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_va_upstream_changes_prev_reviewer_final', type_='foreignkey'
        )
        batch_op.drop_column('previous_reviewer_final_assessment_id')
