"""Mentoring institutes: platform-admin management and the grant guard.

An institute is a cross-project master (``mas_mentor_institute``) attached to
district-level units (``map_mentor_institute_org_unit``) and staffed by users
(``map_mentor_institute_user``). Mentor access is through ordinary unit
grants; the maps only *guard* writing them: ``check_mentor_grant`` refuses a
member any grant outside an attached district's subtree or outside
``MENTOR_ROLES``. Detach and remove soft-deactivate (``is_active``), so they
are reversible and never touch grants.

Policy: docs/policy/organization-model.md, "Mentoring institutes".
Management is admin only, enforced by the callers (``flask mentor-institute``).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app import db
from app.logging.va_logger import log_mentor_institute_action
from app.models import (
    MapMentorInstituteOrgUnit,
    MapMentorInstituteUser,
    MasMentorInstitute,
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services.organization_service import (
    OrganizationError,
    find_unit_by_code,
    normalize_code,
)

# The only roles an institute member may hold, always at org_unit scope.
MENTOR_ROLES = frozenset(
    {
        VaAccessRoles.coder,
        VaAccessRoles.reviewer,
        VaAccessRoles.coding_tester,
        VaAccessRoles.collaborator_pii,
    }
)
_MENTOR_ROLE_NAMES = ", ".join(sorted(role.value for role in MENTOR_ROLES))


# ---------------------------------------------------------------------------
# Management (caller commits)
# ---------------------------------------------------------------------------


def _institute(code: object) -> MasMentorInstitute:
    institute = db.session.scalar(
        sa.select(MasMentorInstitute).where(
            MasMentorInstitute.institute_code == normalize_code(code, what="Institute code")
        )
    )
    if institute is None:
        raise OrganizationError(f"Mentoring institute {code!r} not found.")
    return institute


def _district_unit(project_id: str, unit_code: object) -> MasOrgUnit:
    unit = find_unit_by_code(project_id, unit_code)
    if unit is None:
        raise OrganizationError(f"Unit {unit_code!r} not found in project {project_id}.")
    depth = db.session.scalar(
        sa.select(MasOrgLevel.depth).where(MasOrgLevel.org_level_id == unit.org_level_id)
    )
    if depth != 1:
        raise OrganizationError(
            f"Unit {unit.unit_code!r} is not a district-level unit; mentoring "
            "institutes attach to districts only."
        )
    return unit


def _user_by_email(email: str) -> VaUsers:
    user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email.strip().lower()))
    if user is None:
        raise OrganizationError(f"User {email!r} not found.")
    return user


def create_institute(code: object, name: str, *, actor_user_id=None) -> MasMentorInstitute:
    name = (name or "").strip()
    if not name:
        raise OrganizationError("Institute name is required.")
    code = normalize_code(code, what="Institute code")
    if db.session.scalar(
        sa.select(MasMentorInstitute.institute_id).where(MasMentorInstitute.institute_code == code)
    ):
        raise OrganizationError(f"Mentoring institute {code!r} already exists.")
    institute = MasMentorInstitute(
        institute_code=code, institute_name=name, created_by_user_id=actor_user_id
    )
    db.session.add(institute)
    db.session.flush()
    log_mentor_institute_action(
        action="mentor_institute_created", actor_user_id=actor_user_id, institute=code
    )
    return institute


def set_institute_active(code: object, active: bool, *, actor_user_id=None) -> MasMentorInstitute:
    institute = _institute(code)
    institute.is_active = active
    log_mentor_institute_action(
        action="mentor_institute_activated" if active else "mentor_institute_deactivated",
        actor_user_id=actor_user_id,
        institute=institute.institute_code,
    )
    return institute


def _set_district_link(institute_code, project_id, unit_code, active, actor_user_id):
    institute = _institute(institute_code)
    unit = _district_unit(project_id, unit_code)
    link = db.session.get(MapMentorInstituteOrgUnit, (institute.institute_id, unit.org_unit_id))
    if link is None:
        if not active:
            raise OrganizationError("That institute is not attached to that district.")
        db.session.add(
            MapMentorInstituteOrgUnit(
                institute_id=institute.institute_id,
                org_unit_id=unit.org_unit_id,
                created_by_user_id=actor_user_id,
            )
        )
    else:
        link.is_active = active
    db.session.flush()
    log_mentor_institute_action(
        action="mentor_district_attached" if active else "mentor_district_detached",
        actor_user_id=actor_user_id,
        institute=institute.institute_code,
        project=project_id,
        unit=unit.unit_code,
    )


def attach_district(institute_code, project_id: str, unit_code, *, actor_user_id=None) -> None:
    _set_district_link(institute_code, project_id, unit_code, True, actor_user_id)


def detach_district(institute_code, project_id: str, unit_code, *, actor_user_id=None) -> None:
    _set_district_link(institute_code, project_id, unit_code, False, actor_user_id)


def add_member(institute_code, email: str, *, actor_user_id=None) -> int:
    """Make the user institute staff. Returns how many of their active grants
    the guard would now refuse (project/site scope or non-mentor roles); those
    stay in place until an admin revokes them.
    """
    institute = _institute(institute_code)
    user = _user_by_email(email)
    link = db.session.get(MapMentorInstituteUser, (institute.institute_id, user.user_id))
    if link is None:
        db.session.add(
            MapMentorInstituteUser(
                institute_id=institute.institute_id,
                user_id=user.user_id,
                created_by_user_id=actor_user_id,
            )
        )
    else:
        link.is_active = True
    db.session.flush()
    log_mentor_institute_action(
        action="mentor_member_added",
        actor_user_id=actor_user_id,
        institute=institute.institute_code,
        target=user.user_id,
    )
    return db.session.scalar(
        sa.select(sa.func.count())
        .select_from(VaUserAccessGrants)
        .where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            sa.not_(
                sa.and_(
                    VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                    VaUserAccessGrants.role.in_(MENTOR_ROLES),
                )
            ),
        )
    )


def remove_member(institute_code, email: str, *, actor_user_id=None) -> None:
    institute = _institute(institute_code)
    user = _user_by_email(email)
    link = db.session.get(MapMentorInstituteUser, (institute.institute_id, user.user_id))
    if link is None:
        raise OrganizationError("That user is not staff of that institute.")
    link.is_active = False
    log_mentor_institute_action(
        action="mentor_member_removed",
        actor_user_id=actor_user_id,
        institute=institute.institute_code,
        target=user.user_id,
    )


# ---------------------------------------------------------------------------
# Guard and reads
# ---------------------------------------------------------------------------


def member_user_ids(user_ids) -> set[uuid.UUID]:
    """Which of *user_ids* are active members of an active institute (one query)."""
    user_ids = list(user_ids)
    if not user_ids:
        return set()
    return set(
        db.session.scalars(
            sa.select(MapMentorInstituteUser.user_id)
            .join(
                MasMentorInstitute,
                MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
            )
            .where(
                MapMentorInstituteUser.user_id.in_(user_ids),
                MapMentorInstituteUser.is_active.is_(True),
                MasMentorInstitute.is_active.is_(True),
            )
        ).all()
    )


def check_mentor_grant(user_id, role: VaAccessRoles, unit: MasOrgUnit | None) -> None:
    """Refuse a grant a mentoring institute member may not hold.

    *unit* is the unit of an org_unit-scope grant, or None for any other scope.
    No-op for non-members. Raises OrganizationError with an operator message.
    """
    if user_id not in member_user_ids([user_id]):
        return
    if unit is None:
        raise OrganizationError(
            "This user is staff of a mentoring institute and may only hold "
            "unit-scope grants inside a district the institute is attached to."
        )
    if role not in MENTOR_ROLES:
        raise OrganizationError(
            f"A mentoring institute member may hold only {_MENTOR_ROLE_NAMES}; "
            f"not {role.value}."
        )
    district = sa.orm.aliased(MasOrgUnit, name="mentor_district")
    target = sa.orm.aliased(MasOrgUnit, name="mentored_unit")
    covered = db.session.scalar(
        sa.select(sa.literal(1))
        .select_from(MapMentorInstituteUser)
        .join(
            MasMentorInstitute,
            MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
        )
        .join(
            MapMentorInstituteOrgUnit,
            MapMentorInstituteOrgUnit.institute_id == MapMentorInstituteUser.institute_id,
        )
        .join(district, district.org_unit_id == MapMentorInstituteOrgUnit.org_unit_id)
        .join(
            target,
            sa.and_(
                target.project_id == district.project_id,
                sa.text("mentored_unit.path <@ mentor_district.path"),
            ),
        )
        .where(
            MapMentorInstituteUser.user_id == user_id,
            MapMentorInstituteUser.is_active.is_(True),
            MasMentorInstitute.is_active.is_(True),
            MapMentorInstituteOrgUnit.is_active.is_(True),
            district.is_active.is_(True),
            target.org_unit_id == unit.org_unit_id,
        )
        .limit(1)
    )
    if not covered:
        raise OrganizationError(
            "This user is staff of a mentoring institute: the unit must be inside "
            "a district the institute is attached to."
        )


def mentors_for_unit(unit_id) -> list[tuple[MasMentorInstitute, VaUsers]]:
    """Active mentoring-institute staff whose institute covers *unit_id*.

    Covers means an active attachment to the unit's district-level ancestor
    (or the unit itself). For the district page's separate Mentors listing;
    these people are excluded from the district's staff headcount.
    """
    district = sa.orm.aliased(MasOrgUnit, name="mentor_district")
    target = sa.orm.aliased(MasOrgUnit, name="mentored_unit")
    stmt = (
        sa.select(MasMentorInstitute, VaUsers)
        .select_from(MapMentorInstituteOrgUnit)
        .join(
            MasMentorInstitute,
            MasMentorInstitute.institute_id == MapMentorInstituteOrgUnit.institute_id,
        )
        .join(district, district.org_unit_id == MapMentorInstituteOrgUnit.org_unit_id)
        .join(
            target,
            sa.and_(
                target.project_id == district.project_id,
                sa.text("mentored_unit.path <@ mentor_district.path"),
            ),
        )
        .join(
            MapMentorInstituteUser,
            MapMentorInstituteUser.institute_id == MasMentorInstitute.institute_id,
        )
        .join(VaUsers, VaUsers.user_id == MapMentorInstituteUser.user_id)
        .where(
            target.org_unit_id == unit_id,
            MapMentorInstituteOrgUnit.is_active.is_(True),
            MasMentorInstitute.is_active.is_(True),
            MapMentorInstituteUser.is_active.is_(True),
            district.is_active.is_(True),
        )
        .order_by(MasMentorInstitute.institute_code, VaUsers.name)
    )
    return [(institute, user) for institute, user in db.session.execute(stmt)]
