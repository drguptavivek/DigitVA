"""add submission payload versions

Revision ID: e8f9a0b1c2d3
Revises: d5e6f7a8b9c0
Create Date: 2026-03-23 17:05:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e8f9a0b1c2d3"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_submission_payload_versions",
        sa.Column(
            "payload_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("payload_fingerprint", sa.String(length=128), nullable=False),
        sa.Column(
            "payload_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("version_status", sa.String(length=32), nullable=False),
        sa.Column("created_by_role", sa.String(length=32), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_created_at", sa.DateTime(), nullable=False),
        sa.Column("version_activated_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "version_status IN ('active', 'pending_upstream', 'superseded', 'rejected')",
            name="ck_va_submission_payload_versions_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"]),
        sa.PrimaryKeyConstraint("payload_version_id"),
    )
    op.create_index(
        op.f("ix_va_submission_payload_versions_source_updated_at"),
        "va_submission_payload_versions",
        ["source_updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_payload_versions_va_sid"),
        "va_submission_payload_versions",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_payload_versions_version_created_at"),
        "va_submission_payload_versions",
        ["version_created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_payload_versions_version_status"),
        "va_submission_payload_versions",
        ["version_status"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_payload_versions_sid_status",
        "va_submission_payload_versions",
        ["va_sid", "version_status"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_payload_versions_sid_fingerprint",
        "va_submission_payload_versions",
        ["va_sid", "payload_fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_payload_versions_active_unique",
        "va_submission_payload_versions",
        ["va_sid"],
        unique=True,
        postgresql_where=sa.text("version_status = 'active'"),
    )

    op.add_column(
        "va_submissions",
        sa.Column(
            "active_payload_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_va_submissions_active_payload_version_id",
        "va_submissions",
        "va_submission_payload_versions",
        ["active_payload_version_id"],
        ["payload_version_id"],
    )
    op.create_index(
        op.f("ix_va_submissions_active_payload_version_id"),
        "va_submissions",
        ["active_payload_version_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_va_submissions_active_payload_version_id"),
        table_name="va_submissions",
    )
    op.drop_constraint(
        "fk_va_submissions_active_payload_version_id",
        "va_submissions",
        type_="foreignkey",
    )
    op.drop_column("va_submissions", "active_payload_version_id")

    op.drop_index(
        "ix_va_submission_payload_versions_active_unique",
        table_name="va_submission_payload_versions",
        postgresql_where=sa.text("version_status = 'active'"),
    )
    op.drop_index(
        "ix_va_submission_payload_versions_sid_fingerprint",
        table_name="va_submission_payload_versions",
    )
    op.drop_index(
        "ix_va_submission_payload_versions_sid_status",
        table_name="va_submission_payload_versions",
    )
    op.drop_index(
        op.f("ix_va_submission_payload_versions_version_status"),
        table_name="va_submission_payload_versions",
    )
    op.drop_index(
        op.f("ix_va_submission_payload_versions_version_created_at"),
        table_name="va_submission_payload_versions",
    )
    op.drop_index(
        op.f("ix_va_submission_payload_versions_va_sid"),
        table_name="va_submission_payload_versions",
    )
    op.drop_index(
        op.f("ix_va_submission_payload_versions_source_updated_at"),
        table_name="va_submission_payload_versions",
    )
    op.drop_table("va_submission_payload_versions")
