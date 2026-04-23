"""Project and project-site routes for data-management user management."""

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.scope import user_has_role
from app.models import VaProjectMaster, VaProjectSites, VaSiteMaster, VaStatuses
from app.serializers import (
    serialize_project as _serialize_project,
    serialize_project_site as _serialize_project_site,
)

from ..base import data_management


@data_management.get("/api/projects")
@action_authorized("dm_manage_projects")
def manage_projects():
    """Projects the data-manager can manage."""
    dm_projects = current_user.get_data_manager_projects()
    dm_site_pairs = current_user.get_data_manager_project_sites()
    all_project_ids = dm_projects | {project_id for project_id, _ in dm_site_pairs}

    if user_has_role(current_user, "admin"):
        stmt = (
            sa.select(VaProjectMaster)
            .where(VaProjectMaster.project_status == VaStatuses.active)
            .order_by(VaProjectMaster.project_id)
        )
        projects = db.session.scalars(stmt).all()
        return jsonify({"projects": [_serialize_project(project) for project in projects]})

    if not all_project_ids:
        return jsonify({"projects": []})

    stmt = (
        sa.select(VaProjectMaster)
        .where(
            VaProjectMaster.project_status == VaStatuses.active,
            VaProjectMaster.project_id.in_(list(all_project_ids)),
        )
        .order_by(VaProjectMaster.project_id)
    )
    projects = db.session.scalars(stmt).all()
    return jsonify({"projects": [_serialize_project(project) for project in projects]})


@data_management.get("/api/project-sites")
@action_authorized("dm_manage_project_sites")
def manage_project_sites():
    """Project-sites within the data-manager's scope."""
    project_id = request.args.get("project_id")
    dm_projects = current_user.get_data_manager_projects()
    dm_site_pairs = current_user.get_data_manager_project_sites()

    stmt = (
        sa.select(
            VaProjectSites.project_site_id,
            VaProjectSites.project_id,
            VaProjectSites.site_id,
            VaProjectSites.project_site_status,
            VaProjectSites.coding_enabled,
            VaProjectSites.coding_start_date,
            VaProjectSites.coding_end_date,
            VaProjectSites.daily_coder_limit,
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
    )

    if project_id:
        stmt = stmt.where(VaProjectSites.project_id == project_id)

    if not user_has_role(current_user, "admin"):
        conditions = []
        if dm_projects:
            conditions.append(VaProjectSites.project_id.in_(list(dm_projects)))
        if dm_site_pairs:
            pair_clauses = [
                sa.and_(
                    VaProjectSites.project_id == managed_project_id,
                    VaProjectSites.site_id == managed_site_id,
                )
                for managed_project_id, managed_site_id in dm_site_pairs
            ]
            conditions.append(sa.or_(*pair_clauses))
        if conditions:
            stmt = stmt.where(sa.or_(*conditions))
        else:
            return jsonify({"project_sites": []})

    rows = db.session.execute(
        stmt.order_by(VaProjectSites.project_id, VaProjectSites.site_id)
    ).all()
    return jsonify({"project_sites": [_serialize_project_site(row) for row in rows]})
