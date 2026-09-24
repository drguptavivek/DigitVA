"""Project-level ICD classification: icd10, icd11 or selectable.

Revision ID: 33dea3ea3303
Revises: e7b2c9d4a1f3
Create Date: 2026-09-24 12:00:00.000000

digitva-dus.2. Owner decision 8 in docs/policy/icd10-to-icd11-transition.md;
rules in docs/policy/va-form-project-configuration.md ("5. ICD
classification"). The project setting becomes the only source of a death's
coding classification, so web-form submissions (which have no ODK mapping row)
follow it too.

Additive. Adds va_project_master.icd_classification (server default 'icd10')
and moves each project's per-form values up to it:

- every ODK form of the project carries one value -> that value;
- the forms carry both 'icd10' and 'icd11'     -> 'selectable', so no form
  loses the catalogue its coders were using;
- the project has no ODK form                   -> 'icd10' (the default).

Every project set to something other than 'icd10' is logged. The per-form
column map_project_site_odk.icd_classification is left in place, unchanged,
and is no longer read or written by the app.

Downgrade copies a fixed project setting ('icd10' or 'icd11') back onto that
project's per-form rows, so settings changed after the upgrade survive the
rollback, and leaves a 'selectable' project's forms as they are; then drops
the column. For a project nobody edited this is a no-op on the per-form rows.

The CHECK is added with raw SQL under its final name so the naming convention
in app/__init__.py cannot prefix it twice (see fd232fab5987).
"""

import logging

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "33dea3ea3303"
down_revision = "e7b2c9d4a1f3"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_va_project_master_icd_classification"

log = logging.getLogger("alembic.runtime.migration")


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "icd_classification",
            sa.String(length=16),
            nullable=False,
            server_default="icd10",
        ),
    )
    changed = op.get_bind().execute(
        sa.text(
            """
            UPDATE va_project_master p
               SET icd_classification = f.classification
              FROM (
                    SELECT project_id,
                           CASE WHEN count(DISTINCT icd_classification) > 1
                                THEN 'selectable'
                                ELSE min(icd_classification)
                           END AS classification,
                           string_agg(DISTINCT icd_classification, ',') AS form_values
                      FROM map_project_site_odk
                     GROUP BY project_id
                   ) f
             WHERE f.project_id = p.project_id
               AND f.classification <> 'icd10'
            RETURNING p.project_id, p.icd_classification, f.form_values
            """
        )
    ).all()
    for project_id, classification, form_values in changed:
        log.warning(
            "va_project_master.icd_classification: project %s set to %s "
            "(its ODK forms carried %s)",
            project_id,
            classification,
            form_values,
        )
    op.execute(
        f'ALTER TABLE va_project_master ADD CONSTRAINT "{CHECK_NAME}" '
        "CHECK (icd_classification IN ('icd10', 'icd11', 'selectable'))"
    )


def downgrade():
    op.execute(
        """
        UPDATE map_project_site_odk m
           SET icd_classification = p.icd_classification
          FROM va_project_master p
         WHERE p.project_id = m.project_id
           AND p.icd_classification IN ('icd10', 'icd11')
           AND m.icd_classification <> p.icd_classification
        """
    )
    op.execute(f'ALTER TABLE va_project_master DROP CONSTRAINT IF EXISTS "{CHECK_NAME}"')
    op.drop_column("va_project_master", "icd_classification")
