"""Shared helpers for data-management user/grant routes."""

import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.authz.scope import user_has_role
from app.models import VaAccessRoles, VaProjectSites, VaStatuses, VaUserAccessGrants, VaUsers
from app.authz.grants import (
    grant_project_id_expression as _grant_project_id_expression,
    grant_site_id_expression as _grant_site_id_expression,
)


def _managed_roles():
    return [
        VaAccessRoles.coder,
        VaAccessRoles.coding_tester,
        VaAccessRoles.data_manager,
    ]


def _valid_language_codes():
    from app.models.mas_languages import MasLanguages

    return set(
        db.session.scalars(
            sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)
        ).all()
    )


def _grant_detail_row(grant_id):
    return db.session.execute(
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
            _grant_project_id_expression().label("resolved_project_id"),
            _grant_site_id_expression().label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(VaUserAccessGrants.grant_id == grant_id)
    ).one()


def dm_can_edit_user_email(target_user: VaUsers) -> bool:
    """DM can edit email only for users created by them; admins bypass."""
    if user_has_role(current_user, "admin"):
        return True
    other = target_user.other or {}
    created_by = other.get("created_by_user_id")
    return created_by == str(current_user.user_id)
