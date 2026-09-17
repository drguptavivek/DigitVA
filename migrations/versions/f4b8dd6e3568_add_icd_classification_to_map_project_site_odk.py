"""add icd_classification to map_project_site_odk

Form-level ICD classification setting (icd10 | icd11), default icd10 for
backward compatibility. See docs/planning/icd11-coding-screen-integration-plan.md.

Revision ID: f4b8dd6e3568
Revises: b6edb1b7d01a
Create Date: 2026-09-17 00:05:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "f4b8dd6e3568"
down_revision = "b6edb1b7d01a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "map_project_site_odk",
        sa.Column(
            "icd_classification",
            sa.String(length=8),
            nullable=False,
            server_default="icd10",
        ),
    )
    op.create_check_constraint(
        "ck_map_project_site_odk_icd_classification",
        "map_project_site_odk",
        "icd_classification IN ('icd10', 'icd11')",
    )


def downgrade():
    op.drop_constraint(
        "ck_map_project_site_odk_icd_classification",
        "map_project_site_odk",
        type_="check",
    )
    op.drop_column("map_project_site_odk", "icd_classification")
