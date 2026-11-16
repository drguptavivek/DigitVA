"""Add map_project_members: project roster membership that grants nothing.

Revision ID: d8a2f4c6e1b3
Revises: c7f1d3a5e9b2
Create Date: 2026-11-16

Additive (digitva-plgm): the roster's "Upload users CSV" records who belongs
on a project before a trainer places them in a unit. No authorization path
reads it. Downgrade drops the table and its rows; the accounts and any grants
written by placing a member are untouched.
"""

import sqlalchemy as sa
from alembic import op

revision = "d8a2f4c6e1b3"
down_revision = "c7f1d3a5e9b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "map_project_members",
        sa.Column("project_member_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["va_project_master.project_id"],
            name="fk_map_project_members_project_id_va_project_master",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["va_users.user_id"], name="fk_map_project_members_user_id_va_users",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_user_id"], ["va_users.user_id"],
            name="fk_map_project_members_added_by_user_id_va_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("project_member_id", name="pk_map_project_members"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_map_project_members_project_user"),
    )
    op.create_index("ix_map_project_members_user_id", "map_project_members", ["user_id"])


def downgrade():
    op.drop_index("ix_map_project_members_user_id", table_name="map_project_members")
    op.drop_table("map_project_members")
