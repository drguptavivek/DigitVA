import sqlalchemy as sa
from app import db
from app.models import VaSites
from app.utils import validate_project_id


def va_site_updatesite(site_id, project_id=None, site_name=None, site_abbr=None):
    session = db.session
    va_site = session.scalars(
        sa.select(VaSites).where(VaSites.site_id == site_id)
    ).first()
    if not va_site:
        print(f"Failed [Site ID {site_id} not found.]")
        return
    if project_id:
        if validate_project_id(project_id, session, True):
            va_site.project_id = project_id
        else:
            return
    if site_name:
        va_site.site_name = site_name
    if site_abbr:
        va_site.site_abbr = site_abbr
    session.commit()
    print(f"Success [Site '{site_id}' updated.]")
