import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.models import VaProjectSites, VaStatuses, VaUserAccessGrants, VaUsers
from app.authz.grants import (
    grant_project_id_expression as _grant_project_id_expression,
    grant_site_id_expression as _grant_site_id_expression,
)
from app.serializers import serialize_grant as _serialize_grant


def _project_access_filter(project_id_expression):
    if current_user.is_authenticated and current_user.is_admin():
        return sa.true()
    if current_user.is_authenticated:
        return project_id_expression.in_(list(current_user.get_project_pi_projects()))
    return sa.false()


def _base_grants_select():
    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()
    stmt = (
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
    )
    return stmt, project_id_expression, site_id_expression


def _serialize_grant_by_id(grant_id):
    stmt, _, _ = _base_grants_select()
    row = db.session.execute(
        stmt.where(VaUserAccessGrants.grant_id == grant_id)
    ).one()
    return _serialize_grant(row)
