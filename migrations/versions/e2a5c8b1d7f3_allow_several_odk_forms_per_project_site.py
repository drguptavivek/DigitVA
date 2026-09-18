"""Allow several ODK forms per project-site.

Revision ID: e2a5c8b1d7f3
Revises: b8e3d1f7a2c4
Create Date: 2026-09-18 16:00:00.000000

One DigitVA project accepts submissions from several ODK Central forms over
one connection, so uniqueness on map_project_site_odk moves from
(project_id, site_id) to the whole identity
(project_id, site_id, odk_project_id, odk_form_id). Widening a unique
constraint cannot invalidate existing rows: every pair that was unique
before is still unique under the wider key. Plan:
docs/planning/health-system-organization-model-plan.md (phase 3b).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2a5c8b1d7f3"
down_revision = "c1d4e7f9a3b6"
branch_labels = None
depends_on = None

OLD_NAME = "uq_map_project_site_odk_project_site"
NEW_NAME = "uq_map_project_site_odk_project_site_form"


def upgrade():
    op.drop_constraint(OLD_NAME, "map_project_site_odk", type_="unique")
    op.create_unique_constraint(
        NEW_NAME,
        "map_project_site_odk",
        ["project_id", "site_id", "odk_project_id", "odk_form_id"],
    )


def downgrade():
    # Narrowing back cannot succeed while any project-site maps more than one
    # ODK form, and dropping one of them would orphan its va_forms row and
    # every submission on it. Refuse and let the operator decide.
    duplicates = op.get_bind().execute(
        sa.text(
            """
            SELECT project_id, site_id, count(*) AS mappings
              FROM map_project_site_odk
             GROUP BY project_id, site_id
            HAVING count(*) > 1
             ORDER BY project_id, site_id
            """
        )
    ).all()
    if duplicates:
        detail = ", ".join(
            f"{row.project_id}/{row.site_id} ({row.mappings} forms)" for row in duplicates
        )
        raise RuntimeError(
            "Cannot downgrade past e2a5c8b1d7f3: these project-sites map more "
            f"than one ODK form — {detail}. Remove the extra mappings, and the "
            "va_forms rows and submissions that belong to them, first."
        )

    op.drop_constraint(NEW_NAME, "map_project_site_odk", type_="unique")
    op.create_unique_constraint(OLD_NAME, "map_project_site_odk", ["project_id", "site_id"])
