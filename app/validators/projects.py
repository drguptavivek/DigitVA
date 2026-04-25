"""Project and site setup validators.

These helpers protect legacy setup services from creating duplicate project or
site identifiers and from linking records to missing project/site masters.
"""

import sqlalchemy as sa

from app.models import VaResearchProjects, VaSites
from app.validators.users import fail


def validate_project_id(project_id, session, foreignkey=False):
    if not len(project_id) == 6:
        return fail(f"Inadequate project_id '{project_id}' length.")
    existing_project_id = session.scalar(
        sa.select(VaResearchProjects.project_id).where(
            VaResearchProjects.project_id == project_id
        )
    )
    if not existing_project_id and foreignkey:
        return fail(f"No research project with project_id '{project_id}' exists.")
    if existing_project_id and not foreignkey:
        return fail(f"Project with project_id '{project_id}' already exists.")
    return True


def validate_site_id(site_id, session, foreignkey=False):
    if not len(site_id) == 4:
        return fail(f"Inadequate site_id '{site_id}' length.")
    existing_site_id = session.scalar(
        sa.select(VaSites.site_id).where(VaSites.site_id == site_id)
    )
    if not existing_site_id and foreignkey:
        return fail(f"No site with site_id '{site_id}' exists.")
    if existing_site_id and not foreignkey:
        return fail(f"Site with side_id '{site_id}' already exists.")
    return True


def validate_project_code(project_code):
    if project_code and len(project_code) > 6:
        return fail(f"Project code '{project_code} length exceeds 6 characters.")
    return True
