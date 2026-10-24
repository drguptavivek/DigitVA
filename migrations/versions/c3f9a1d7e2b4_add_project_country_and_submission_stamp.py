"""Project country (ISO3) and the per-submission country stamp.

Revision ID: c3f9a1d7e2b4
Revises: 89f755b1156c
Create Date: 2026-10-24 23:00:00.000000

Adds va_project_master.project_country_iso3 and va_submissions.va_country_iso3
(both nullable String(3)). Backfill: a project takes its forms' form_smartvacountry
when every one of its forms agrees (else it stays null); each submission is then
stamped from its project's country. Nothing is dropped or overwritten, and
form_smartvacountry is kept. Counts go to the migration log. Downgrade drops
both columns (the stamp is derived data; the form column still holds the old
setting).
"""
import logging

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3f9a1d7e2b4"
down_revision = "89f755b1156c"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade():
    op.add_column(
        "va_project_master", sa.Column("project_country_iso3", sa.String(3), nullable=True)
    )
    op.add_column(
        "va_submissions", sa.Column("va_country_iso3", sa.String(3), nullable=True)
    )
    bind = op.get_bind()
    projects = bind.execute(sa.text("""
        UPDATE va_project_master p
        SET project_country_iso3 = f.country
        FROM (
            SELECT project_id, min(upper(form_smartvacountry)) AS country
            FROM va_forms
            GROUP BY project_id
            HAVING count(DISTINCT upper(form_smartvacountry)) = 1
               AND min(upper(form_smartvacountry)) ~ '^[A-Z]{3}$'
        ) f
        WHERE f.project_id = p.project_id AND p.project_country_iso3 IS NULL
    """)).rowcount
    left_null = bind.execute(sa.text(
        "SELECT count(*) FROM va_project_master WHERE project_country_iso3 IS NULL"
    )).scalar()
    stamped = bind.execute(sa.text("""
        UPDATE va_submissions s
        SET va_country_iso3 = p.project_country_iso3
        FROM va_forms f, va_project_master p
        WHERE f.form_id = s.va_form_id
          AND p.project_id = f.project_id
          AND p.project_country_iso3 IS NOT NULL
          AND s.va_country_iso3 IS NULL
    """)).rowcount
    log.info(
        "project country: %s project(s) set from agreeing forms, %s left null "
        "(no forms or forms disagree); %s submission(s) stamped",
        projects, left_null, stamped,
    )


def downgrade():
    op.drop_column("va_submissions", "va_country_iso3")
    op.drop_column("va_project_master", "project_country_iso3")
