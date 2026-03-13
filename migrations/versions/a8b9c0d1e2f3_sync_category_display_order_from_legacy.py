"""sync category display order from legacy table

Revision ID: a8b9c0d1e2f3
Revises: f1a2b3c4d5e6
Create Date: 2026-03-13 14:35:00.000000
"""

from alembic import op


revision = "a8b9c0d1e2f3"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE mas_category_display_config AS display_cfg
        SET display_order = legacy.display_order
        FROM mas_category_order AS legacy
        WHERE display_cfg.form_type_id = legacy.form_type_id
          AND display_cfg.category_code = legacy.category_code
          AND display_cfg.display_order IS DISTINCT FROM legacy.display_order
        """
    )


def downgrade():
    # No-op. This data sync aligns duplicate order columns during cutover.
    pass
