"""add demo expiry timestamps to coding artifacts

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15 12:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_final_assessments",
        sa.Column("demo_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f("ix_va_final_assessments_demo_expires_at"),
        "va_final_assessments",
        ["demo_expires_at"],
        unique=False,
    )

    op.add_column(
        "va_narrative_assessments",
        sa.Column("demo_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f("ix_va_narrative_assessments_demo_expires_at"),
        "va_narrative_assessments",
        ["demo_expires_at"],
        unique=False,
    )

    op.add_column(
        "va_social_autopsy_analyses",
        sa.Column("demo_expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analyses_demo_expires_at"),
        "va_social_autopsy_analyses",
        ["demo_expires_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_va_social_autopsy_analyses_demo_expires_at"),
        table_name="va_social_autopsy_analyses",
    )
    op.drop_column("va_social_autopsy_analyses", "demo_expires_at")

    op.drop_index(
        op.f("ix_va_narrative_assessments_demo_expires_at"),
        table_name="va_narrative_assessments",
    )
    op.drop_column("va_narrative_assessments", "demo_expires_at")

    op.drop_index(
        op.f("ix_va_final_assessments_demo_expires_at"),
        table_name="va_final_assessments",
    )
    op.drop_column("va_final_assessments", "demo_expires_at")
