from app import db
from app.models import VaSites
from app.utils import validate_project_id, validate_site_id


def va_site_addsite(site_id, project_id, site_name, site_abbr):
    session = db.session
    if not all(
        [
            validate_site_id(site_id, session, False),
            validate_project_id(project_id, session, True),
        ]
    ):
        return
    va_site = VaSites(
        site_id=site_id,
        project_id=project_id,
        site_name=site_name,
        site_abbr=site_abbr,
    )
    session.add(va_site)
    session.commit()
    print(f"Success [Site '{site_id}' added.]")
