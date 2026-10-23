"""Rename the doubled mas_ui_string_override source CHECK constraint.

Revision ID: 89f755b1156c
Revises: q7c2n5x9d4b8
Create Date: 2026-10-24 22:00:00.000000

q7c2n5x9d4b8 passed the full name to a metadata with the ck_%(table_name)s_
naming convention, so the database got
ck_mas_ui_string_override_ck_mas_ui_string_override_source. A rename only:
the check itself is unchanged and no row is touched.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "89f755b1156c"
down_revision = "q7c2n5x9d4b8"
branch_labels = None
depends_on = None

TABLE = "mas_ui_string_override"
DOUBLED = "ck_mas_ui_string_override_ck_mas_ui_string_override_source"
FIXED = "ck_mas_ui_string_override_source"


def upgrade():
    op.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT {DOUBLED} TO {FIXED}")


def downgrade():
    op.execute(f"ALTER TABLE {TABLE} RENAME CONSTRAINT {FIXED} TO {DOUBLED}")
