"""add_narrative_qa_module

Revision ID: a383b3c82328
Revises: p3q7r9s1t2u5
Create Date: 2026-03-12 10:15:12.937868

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a383b3c82328'
down_revision = 'p3q7r9s1t2u5'
branch_labels = None
depends_on = None


status_enum = postgresql.ENUM("active", "deactive", name="status_enum", create_type=False)


def upgrade():
    op.add_column(
        'va_project_master',
        sa.Column('narrative_qa_enabled', sa.Boolean(), nullable=False, server_default='false'),
    )

    op.create_table(
        'va_narrative_assessments',
        sa.Column('va_nqa_id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('va_sid', sa.String(64),
                  sa.ForeignKey('va_submissions.va_sid', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('va_nqa_by', sa.Uuid(as_uuid=True),
                  sa.ForeignKey('va_users.user_id'),
                  nullable=False, index=True),
        sa.Column('va_nqa_length',       sa.SmallInteger(), nullable=False),
        sa.Column('va_nqa_pos_symptoms', sa.SmallInteger(), nullable=False),
        sa.Column('va_nqa_neg_symptoms', sa.SmallInteger(), nullable=False),
        sa.Column('va_nqa_chronology',   sa.SmallInteger(), nullable=False),
        sa.Column('va_nqa_doc_review',   sa.SmallInteger(), nullable=False),
        sa.Column('va_nqa_comorbidity',  sa.SmallInteger(), nullable=False),
        sa.Column('va_nqa_score',        sa.SmallInteger(), nullable=False),
        sa.Column('va_nqa_status', status_enum, nullable=False),
        sa.Column('va_nqa_createdat', sa.DateTime(), nullable=False),
        sa.Column('va_nqa_updatedat', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('va_sid', 'va_nqa_by', name='uq_nqa_sid_by'),
    )


def downgrade():
    op.drop_table('va_narrative_assessments')
    op.drop_column('va_project_master', 'narrative_qa_enabled')
