"""add validation_err to va_submission_payload_versions

Revision ID: f2031819b3aa
Revises: fd232fab5987
Create Date: 2026-09-20 14:40:57.626503

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f2031819b3aa'
down_revision = 'fd232fab5987'
branch_labels = None
depends_on = None


def upgrade():
    # Additive, reversible: server-derived disagreements between the
    # client's own "valid: true" and this application's own re-evaluation
    # of relevant/constraint over the same answers (beads digitva-cal.2).
    # Never enforced, per-version rather than per-submission -- see
    # app/models/va_submission_payload_versions.py.
    op.add_column(
        'va_submission_payload_versions',
        sa.Column(
            'validation_err',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade():
    op.drop_column('va_submission_payload_versions', 'validation_err')
