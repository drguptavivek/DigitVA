"""add created_by_user_id to va_user_access_grants

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-04-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_user_access_grants",
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_va_user_access_grants_created_by",
        "va_user_access_grants",
        "va_users",
        ["created_by_user_id"],
        ["user_id"],
    )


def downgrade():
    op.drop_constraint(
        "fk_va_user_access_grants_created_by",
        "va_user_access_grants",
        type_="foreignkey",
    )
    op.drop_column("va_user_access_grants", "created_by_user_id")
