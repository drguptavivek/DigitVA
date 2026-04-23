"""Shared helpers for data-management route modules."""

from functools import wraps

import sqlalchemy as sa
from flask import g, request
from flask_login import current_user

from app import db
from app.authz.scope import (
    user_can_manage_grant_scope,
    user_can_manage_target_user,
    user_has_role,
)
from app.models import VaAccessScopeTypes, VaProjectSites, VaStatuses, VaUserAccessGrants
from app.authz.grants import resolve_scope_from_payload as _resolve_scope_from_payload
from app.http.responses import json_error as _json_error

from .base import log


def dm_can_manage_scope(user, role, scope_type, resolved_project_id, project_site_id):
    """Return whether *user* can create or toggle a grant for the given scope."""
    return user_can_manage_grant_scope(
        user,
        role,
        scope_type,
        resolved_project_id,
        project_site_id,
    )


def dm_grant_filter(project_id_expression):
    """SQLAlchemy WHERE clause limiting grants to the DM's managed scope."""
    if user_has_role(current_user, "admin"):
        return sa.true()

    dm_projects = current_user.get_data_manager_projects()
    dm_site_pairs = current_user.get_data_manager_project_sites()

    conditions = []
    if dm_projects:
        conditions.append(project_id_expression.in_(list(dm_projects)))
    if dm_site_pairs:
        project_site_ids = [
            db.session.scalar(
                sa.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == project_id,
                    VaProjectSites.site_id == site_id,
                    VaProjectSites.project_site_status == VaStatuses.active,
                )
            )
            for project_id, site_id in dm_site_pairs
        ]
        project_site_ids = [value for value in project_site_ids if value is not None]
        if project_site_ids:
            conditions.append(VaUserAccessGrants.project_site_id.in_(project_site_ids))

    if not conditions:
        return sa.false()
    return sa.or_(*conditions)


def dm_can_manage_target_user(target_user_id) -> bool:
    """Return whether the current caller may manage the target user."""
    return user_can_manage_target_user(current_user, target_user_id)


def require_dm_scope(f):
    """Structural authz gate for grant mutation endpoints."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        grant_id = kwargs.get("grant_id")

        if grant_id is not None:
            grant = db.session.get(VaUserAccessGrants, grant_id)
            if not grant:
                return _json_error("Grant not found.", 404)
            if grant.scope_type == VaAccessScopeTypes.project:
                resolved_project_id = grant.project_id
            elif grant.scope_type == VaAccessScopeTypes.project_site:
                project_site = db.session.get(VaProjectSites, grant.project_site_id)
                resolved_project_id = project_site.project_id if project_site else None
            else:
                return _json_error("Invalid scope type.", 400)
            ok, err = dm_can_manage_scope(
                current_user,
                grant.role,
                grant.scope_type,
                resolved_project_id,
                grant.project_site_id,
            )
        else:
            payload = request.get_json(silent=True) or {}
            try:
                role, scope_type, resolved_project_id, project_site_id = (
                    _resolve_scope_from_payload(payload)
                )
            except ValueError as exc:
                return _json_error(str(exc), 400)
            ok, err = dm_can_manage_scope(
                current_user,
                role,
                scope_type,
                resolved_project_id,
                project_site_id,
            )
            g.dm_scope = (role, scope_type, resolved_project_id, project_site_id)

        if not ok:
            log.warning(
                "Grant scope denied: user=%s path=%s reason=%s",
                current_user.get_id(),
                request.path,
                err,
            )
            return _json_error(err, 403)

        return f(*args, **kwargs)

    return wrapper
