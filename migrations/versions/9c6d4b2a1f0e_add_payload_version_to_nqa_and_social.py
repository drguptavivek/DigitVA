"""Add payload-version linkage to NQA and Social Autopsy artifacts.

Revision ID: 9c6d4b2a1f0e
Revises: 8d52cf78e833
Create Date: 2026-04-02 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9c6d4b2a1f0e"
down_revision = "8d52cf78e833"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "va_narrative_assessments",
        sa.Column("payload_version_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_narrative_assessments_payload_version_id",
        "va_narrative_assessments",
        ["payload_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_narrative_assessments_payload_version_id",
        "va_narrative_assessments",
        "va_submission_payload_versions",
        ["payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "va_social_autopsy_analyses",
        sa.Column("payload_version_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_social_autopsy_analyses_payload_version_id",
        "va_social_autopsy_analyses",
        ["payload_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_social_autopsy_analyses_payload_version_id",
        "va_social_autopsy_analyses",
        "va_submission_payload_versions",
        ["payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE va_narrative_assessments AS nqa
        SET payload_version_id = s.active_payload_version_id
        FROM va_submissions AS s
        WHERE s.va_sid = nqa.va_sid
          AND s.active_payload_version_id IS NOT NULL
          AND nqa.payload_version_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE va_social_autopsy_analyses AS saa
        SET payload_version_id = s.active_payload_version_id
        FROM va_submissions AS s
        WHERE s.va_sid = saa.va_sid
          AND s.active_payload_version_id IS NOT NULL
          AND saa.payload_version_id IS NULL
        """
    )

    op.drop_constraint(
        "uq_nqa_sid_by",
        "va_narrative_assessments",
        type_="unique",
    )
    op.drop_constraint(
        "uq_social_autopsy_analysis_sid_by",
        "va_social_autopsy_analyses",
        type_="unique",
    )

    op.create_index(
        "ix_va_narrative_assessments_active_sid_by_unique",
        "va_narrative_assessments",
        ["va_sid", "va_nqa_by"],
        unique=True,
        postgresql_where=sa.text("va_nqa_status = 'active'"),
    )
    op.create_index(
        "ix_va_social_autopsy_analyses_active_sid_by_unique",
        "va_social_autopsy_analyses",
        ["va_sid", "va_saa_by"],
        unique=True,
        postgresql_where=sa.text("va_saa_status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_va_social_autopsy_analyses_active_sid_by_unique",
        table_name="va_social_autopsy_analyses",
    )
    op.drop_index(
        "ix_va_narrative_assessments_active_sid_by_unique",
        table_name="va_narrative_assessments",
    )

    op.create_unique_constraint(
        "uq_social_autopsy_analysis_sid_by",
        "va_social_autopsy_analyses",
        ["va_sid", "va_saa_by"],
    )
    op.create_unique_constraint(
        "uq_nqa_sid_by",
        "va_narrative_assessments",
        ["va_sid", "va_nqa_by"],
    )

    op.drop_constraint(
        "fk_va_social_autopsy_analyses_payload_version_id",
        "va_social_autopsy_analyses",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_social_autopsy_analyses_payload_version_id",
        table_name="va_social_autopsy_analyses",
    )
    op.drop_column("va_social_autopsy_analyses", "payload_version_id")

    op.drop_constraint(
        "fk_va_narrative_assessments_payload_version_id",
        "va_narrative_assessments",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_narrative_assessments_payload_version_id",
        table_name="va_narrative_assessments",
    )
    op.drop_column("va_narrative_assessments", "payload_version_id")
