"""Add data-manager access role and triage table.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-14 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE access_role_enum ADD VALUE IF NOT EXISTS 'data_manager'")

    op.drop_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        """
        (role = 'admin' AND scope_type = 'global') OR
        (role = 'project_pi' AND scope_type = 'project') OR
        (role = 'site_pi' AND scope_type = 'project_site') OR
        (role IN ('collaborator', 'coder', 'reviewer', 'data_manager') AND scope_type IN ('project', 'project_site'))
        """,
    )

    op.create_table(
        "va_data_manager_review",
        sa.Column("va_dmreview_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("va_dmreview_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_dmreview_reason", sa.String(length=64), nullable=False),
        sa.Column("va_dmreview_other", sa.Text(), nullable=True),
        sa.Column(
            "va_dmreview_status",
            postgresql.ENUM(
                "pending",
                "active",
                "deactive",
                name="status_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("va_dmreview_createdat", sa.DateTime(), nullable=False),
        sa.Column("va_dmreview_updatedat", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["va_dmreview_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"]),
        sa.PrimaryKeyConstraint("va_dmreview_id"),
    )
    op.create_index(
        op.f("ix_va_data_manager_review_va_dmreview_createdat"),
        "va_data_manager_review",
        ["va_dmreview_createdat"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_data_manager_review_va_dmreview_by"),
        "va_data_manager_review",
        ["va_dmreview_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_data_manager_review_va_dmreview_id"),
        "va_data_manager_review",
        ["va_dmreview_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_data_manager_review_va_dmreview_status"),
        "va_data_manager_review",
        ["va_dmreview_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_data_manager_review_va_sid"),
        "va_data_manager_review",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        "uq_va_data_manager_review_active_sid",
        "va_data_manager_review",
        ["va_sid"],
        unique=True,
        postgresql_where=sa.text("va_dmreview_status = 'active'"),
    )


def downgrade():
    op.drop_index("uq_va_data_manager_review_active_sid", table_name="va_data_manager_review")
    op.drop_index(op.f("ix_va_data_manager_review_va_sid"), table_name="va_data_manager_review")
    op.drop_index(
        op.f("ix_va_data_manager_review_va_dmreview_status"),
        table_name="va_data_manager_review",
    )
    op.drop_index(
        op.f("ix_va_data_manager_review_va_dmreview_id"),
        table_name="va_data_manager_review",
    )
    op.drop_index(
        op.f("ix_va_data_manager_review_va_dmreview_by"),
        table_name="va_data_manager_review",
    )
    op.drop_index(
        op.f("ix_va_data_manager_review_va_dmreview_createdat"),
        table_name="va_data_manager_review",
    )
    op.drop_table("va_data_manager_review")

    op.drop_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        type_="check",
    )
    op.create_check_constraint(
        "ck_va_user_access_grants_role_scope",
        "va_user_access_grants",
        """
        (role = 'admin' AND scope_type = 'global') OR
        (role = 'project_pi' AND scope_type = 'project') OR
        (role = 'site_pi' AND scope_type = 'project_site') OR
        (role IN ('collaborator', 'coder', 'reviewer') AND scope_type IN ('project', 'project_site'))
        """,
    )
