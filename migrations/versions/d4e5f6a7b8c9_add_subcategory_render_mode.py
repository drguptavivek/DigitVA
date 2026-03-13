"""add subcategory render mode

Revision ID: d4e5f6a7b8c9
Revises: c7f1d2e3a4b5
Create Date: 2026-03-13 12:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c7f1d2e3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mas_subcategory_order",
        sa.Column(
            "render_mode",
            sa.String(length=32),
            nullable=False,
            server_default="default",
        ),
    )

    op.execute(
        """
        UPDATE mas_subcategory_order
        SET render_mode = 'media_gallery'
        WHERE category_code = 'vanarrationanddocuments'
          AND subcategory_code IN ('medical_documents', 'death_documents')
        """
    )

    op.alter_column(
        "mas_subcategory_order",
        "render_mode",
        server_default=None,
    )


def downgrade():
    op.drop_column("mas_subcategory_order", "render_mode")
