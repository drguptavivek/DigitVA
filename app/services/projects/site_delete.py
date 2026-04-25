import sqlalchemy as sa
from app import db
from app.models import VaSites, VaStatuses


def va_site_deletesite(site_id):
    session = db.session
    va_site = session.scalars(
        sa.select(VaSites).where(VaSites.site_id == site_id)
    ).first()
    if not va_site:
        print(f"Failed [Site ID {site_id} not found.]")
        return
    va_site.site_status = VaStatuses.deactive
    session.commit()
    print(f"Success [Site '{site_id}' deleted.]")
