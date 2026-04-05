"""add FK index on mas_pii_access_log.form_type_id

Missing index on the FK column causes a full table scan on every UPDATE
to mas_form_types (one scan per FK constraint check). Currently harmless
because the table is empty, but will become expensive once PII access
log entries accumulate.

Revision ID: d1e2f3a4b5c6
Revises: cc557953614c
Create Date: 2026-04-05

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'cc557953614c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_mas_pii_access_log_form_type_id',
        'mas_pii_access_log',
        ['form_type_id'],
    )


def downgrade():
    op.drop_index('ix_mas_pii_access_log_form_type_id', table_name='mas_pii_access_log')
