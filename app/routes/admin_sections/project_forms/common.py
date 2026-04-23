"""Shared helpers for admin project-form mapping routes."""

import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster, VaProjectSites, VaSiteMaster, VaStatuses


def get_active_project_site(project_id: str, site_id: str):
    return db.session.scalar(
        sa.select(VaProjectSites)
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_id == project_id,
            VaProjectSites.site_id == site_id,
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
    )
