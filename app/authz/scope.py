from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocations,
    VaAllocation,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)


def user_is_active(user) -> bool:
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "user_status", None) == VaStatuses.active
    )


def user_has_role(user, role: str) -> bool:
    return {
        "admin": user.is_admin,
        "project_pi": user.is_project_pi,
        "site_pi": user.is_site_pi,
        "data_manager": user.is_data_manager,
        "collaborator": user.is_collaborator,
        "coder": user.is_coder,
        "coding_tester": user.is_coding_tester,
        "reviewer": user.is_reviewer,
    }[role]()


def user_has_any_scope(user, role: str) -> bool:
    if role == "admin":
        return user.is_admin()
    if role == "project_pi":
        return bool(user.get_project_pi_projects())
    if role == "site_pi":
        return bool(user.get_site_pi_project_sites())
    if role == "data_manager":
        return bool(user.get_data_manager_projects() or user.get_data_manager_project_sites())
    if role == "collaborator":
        return bool(user.get_collaborator_projects() or user.get_collaborator_project_sites())
    if role == "coder":
        return bool(user.get_coder_va_forms())
    if role == "coding_tester":
        return bool(user.get_coding_tester_va_forms())
    if role == "reviewer":
        return bool(user.get_reviewer_va_forms())
    return False


def user_has_resource_scope(
    user,
    role: str,
    *,
    project_id: str | None = None,
    site_id: str | None = None,
    form_id: str | None = None,
) -> bool:
    if role == "admin":
        return user.is_admin()
    if role == "project_pi":
        return bool(project_id) and user.has_project_pi_submission_access(project_id)
    if role == "site_pi":
        return bool(project_id and site_id) and user.has_site_pi_submission_access(
            project_id, site_id
        )
    if role == "data_manager":
        if form_id:
            return user.has_data_manager_form_access(form_id)
        return bool(project_id and site_id) and user.has_data_manager_submission_access(
            project_id, site_id
        )
    if role == "collaborator":
        return bool(project_id and site_id) and user.has_collaborator_submission_access(
            project_id, site_id
        )
    if role == "coder":
        return user_has_form_access(user, form_id, "coder")
    if role == "coding_tester":
        return bool(form_id) and form_id in user.get_coding_tester_va_forms()
    if role == "reviewer":
        return user_has_form_access(user, form_id, "reviewer")
    return False


def user_has_form_access(user, form_id: str | None, role: str | None = None) -> bool:
    if not form_id:
        return False
    if role == "coder":
        return form_id in user.get_coder_va_forms()
    if role == "reviewer":
        return form_id in user.get_reviewer_va_forms()
    if role == "sitepi":
        return form_id in user.get_site_pi_va_forms()
    if role == "coding_tester":
        return form_id in user.get_coding_tester_va_forms()
    if role:
        return role in (user.permission or {}) and form_id in user.permission[role]
    if form_id in user.get_coder_va_forms():
        return True
    if form_id in user.get_reviewer_va_forms():
        return True
    if form_id in user.get_site_pi_va_forms():
        return True
    if form_id in user.get_coding_tester_va_forms():
        return True
    if user.has_data_manager_form_access(form_id):
        return True
    for legacy_role, va_forms in (user.permission or {}).items():
        if legacy_role in {"coder", "reviewer", "sitepi", "coding_tester"}:
            continue
        if form_id in va_forms:
            return True
    return False


def user_has_coding_form_access(user, form_id: str | None) -> bool:
    if not form_id:
        return False
    return bool(
        form_id in user.get_coder_va_forms()
        or form_id in user.get_coding_tester_va_forms()
    )


def user_has_dm_like_submission_access(user, project_id: str, site_id: str) -> bool:
    if user.has_data_manager_submission_access(project_id, site_id):
        return True
    if user.has_project_pi_submission_access(project_id):
        return True
    if user.has_site_pi_submission_access(project_id, site_id):
        return True
    return False


def user_can_manage_grant_scope(
    user,
    role,
    scope_type,
    resolved_project_id,
    project_site_id,
) -> tuple[bool, str | None]:
    if user.is_admin():
        if role not in {VaAccessRoles.coder, VaAccessRoles.coding_tester, VaAccessRoles.data_manager}:
            return False, "Only coder, coding_tester, or data_manager roles may be assigned from this interface."
        return True, None
    if role not in {VaAccessRoles.coder, VaAccessRoles.coding_tester, VaAccessRoles.data_manager}:
        return False, "Data-managers may only assign coder, coding_tester, or data_manager roles."

    dm_projects = user.get_data_manager_projects()
    dm_site_pairs = user.get_data_manager_project_sites()

    if scope_type == VaAccessScopeTypes.project:
        if resolved_project_id not in dm_projects:
            return False, "You do not have access to assign grants at project level for this project."
        return True, None

    if scope_type == VaAccessScopeTypes.project_site:
        project_site = db.session.get(VaProjectSites, project_site_id)
        if not project_site or project_site.project_site_status != VaStatuses.active:
            return False, "Active project-site mapping not found."
        if project_site.project_id in dm_projects:
            return True, None
        if (project_site.project_id, project_site.site_id) in dm_site_pairs:
            return True, None
        return False, "You do not have access to assign grants for this site."

    return False, "Invalid scope type."


def user_can_manage_target_user(user, target_user_id) -> bool:
    if user.is_admin():
        return True

    project_id_expression = sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id,
        ),
        else_=VaProjectSites.project_id,
    )

    dm_projects = user.get_data_manager_projects()
    dm_site_pairs = user.get_data_manager_project_sites()
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
        return False

    return bool(
        db.session.scalar(
            sa.select(VaUserAccessGrants.grant_id)
            .outerjoin(
                VaProjectSites,
                VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
            )
            .where(
                VaUserAccessGrants.user_id == target_user_id,
                VaUserAccessGrants.grant_status == VaStatuses.active,
                VaUserAccessGrants.role.in_(
                    [
                        VaAccessRoles.coder,
                        VaAccessRoles.coding_tester,
                        VaAccessRoles.data_manager,
                    ]
                ),
                sa.or_(*conditions),
            )
            .limit(1)
        )
    )


def user_has_active_allocation(
    user,
    allocation_for: VaAllocation,
    *,
    va_sid: str | None = None,
) -> bool:
    filters = [
        VaAllocations.va_allocated_to == user.user_id,
        VaAllocations.va_allocation_for == allocation_for,
        VaAllocations.va_allocation_status == VaStatuses.active,
    ]
    if va_sid is not None:
        filters.append(VaAllocations.va_sid == va_sid)
    return bool(
        db.session.scalar(
            sa.select(VaAllocations.va_sid).where(*filters).limit(1)
        )
    )


def user_requires_allocation_bound_attachment_access(
    user,
    form_id: str | None,
) -> bool:
    if not form_id:
        return False
    if user.is_admin():
        return False
    return bool(
        (
            (user_has_role(user, "coder") or user_has_role(user, "coding_tester"))
            and user_has_coding_form_access(user, form_id)
        )
        or (
            user_has_role(user, "reviewer")
            and user_has_form_access(user, form_id, "reviewer")
        )
    )
