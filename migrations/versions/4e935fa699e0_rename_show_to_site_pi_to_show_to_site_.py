"""rename_show_to_site_pi_to_show_to_site_pi_datamanager

Revision ID: 4e935fa699e0
Revises: 9f1a2b3c4d5e
Create Date: 2026-03-18 11:11:25.190322

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e935fa699e0'
down_revision = '9f1a2b3c4d5e'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "mas_category_display_config",
        "show_to_site_pi",
        new_column_name="show_to_site_pi_datamanager",
    )


def downgrade():
    op.alter_column(
        "mas_category_display_config",
        "show_to_site_pi_datamanager",
        new_column_name="show_to_site_pi",
    )
