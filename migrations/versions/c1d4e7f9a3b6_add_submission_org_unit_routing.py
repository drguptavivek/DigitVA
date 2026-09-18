"""Route submissions to organization units.

Revision ID: c1d4e7f9a3b6
Revises: e5f6a7b8c9d1
Create Date: 2026-09-18 12:00:00.000000

Additive only. Adds a fallback unit to each ODK form mapping and four
routing columns to va_submissions. Every column is nullable and every
existing submission stays unrouted (org_unit_id NULL), which is exactly
what a project without an organization tree means. Plan:
docs/planning/health-system-organization-model-plan.md (phase 3).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d4e7f9a3b6"
down_revision = "e5f6a7b8c9d1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "map_project_site_odk",
        sa.Column("org_unit_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_map_project_site_odk_org_unit",
        "map_project_site_odk",
        "mas_org_unit",
        ["org_unit_id"],
        ["org_unit_id"],
    )

    op.add_column("va_submissions", sa.Column("org_unit_id", sa.Uuid(), nullable=True))
    op.add_column(
        "va_submissions", sa.Column("org_unit_resolution", sa.String(length=16), nullable=True)
    )
    op.add_column("va_submissions", sa.Column("org_unit_pinned_by", sa.Uuid(), nullable=True))
    op.add_column(
        "va_submissions",
        sa.Column("org_unit_pinned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_va_submissions_org_unit",
        "va_submissions",
        "mas_org_unit",
        ["org_unit_id"],
        ["org_unit_id"],
    )
    op.create_foreign_key(
        "fk_va_submissions_org_unit_pinned_by",
        "va_submissions",
        "va_users",
        ["org_unit_pinned_by"],
        ["user_id"],
    )
    op.create_check_constraint(
        "ck_va_submissions_org_unit_resolution_pair",
        "va_submissions",
        "(org_unit_id IS NULL AND org_unit_resolution IS NULL) OR "
        "(org_unit_id IS NOT NULL AND org_unit_resolution IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_va_submissions_org_unit_resolution_value",
        "va_submissions",
        "org_unit_resolution IS NULL OR "
        "org_unit_resolution IN ('form_field', 'mapping_fallback', 'manual')",
    )
    op.create_check_constraint(
        "ck_va_submissions_org_unit_pin_manual",
        "va_submissions",
        "(org_unit_pinned_by IS NULL AND org_unit_pinned_at IS NULL) OR "
        "org_unit_resolution = 'manual'",
    )
    op.create_index("ix_va_submissions_org_unit_id", "va_submissions", ["org_unit_id"])
    op.create_index(
        "ix_va_submissions_org_unit_resolution",
        "va_submissions",
        ["org_unit_id", "org_unit_resolution"],
    )


def downgrade():
    # Routing is derived state: it is recomputed from the payload on the next
    # sync, and a manual pin is the only part that cannot be. Warn rather than
    # fail, since dropping the columns is what the operator asked for.
    pinned = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM va_submissions WHERE org_unit_resolution = 'manual'"
        )
    ).scalar_one()
    if pinned:
        print(
            f"WARNING: discarding {pinned} manually pinned submission unit(s); "
            "they cannot be recomputed from the payload."
        )

    op.drop_index("ix_va_submissions_org_unit_resolution", "va_submissions")
    op.drop_index("ix_va_submissions_org_unit_id", "va_submissions")
    for name in (
        "ck_va_submissions_org_unit_pin_manual",
        "ck_va_submissions_org_unit_resolution_value",
        "ck_va_submissions_org_unit_resolution_pair",
    ):
        for candidate in (name, f"ck_va_submissions_{name}"):
            op.execute(
                f'ALTER TABLE va_submissions DROP CONSTRAINT IF EXISTS "{candidate}"'
            )
    op.drop_constraint(
        "fk_va_submissions_org_unit_pinned_by", "va_submissions", type_="foreignkey"
    )
    op.drop_constraint("fk_va_submissions_org_unit", "va_submissions", type_="foreignkey")
    op.drop_column("va_submissions", "org_unit_pinned_at")
    op.drop_column("va_submissions", "org_unit_pinned_by")
    op.drop_column("va_submissions", "org_unit_resolution")
    op.drop_column("va_submissions", "org_unit_id")

    op.drop_constraint(
        "fk_map_project_site_odk_org_unit", "map_project_site_odk", type_="foreignkey"
    )
    op.drop_column("map_project_site_odk", "org_unit_id")
