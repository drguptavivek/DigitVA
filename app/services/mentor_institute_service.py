"""Mentoring institutes: platform-admin management and the grant guard.

An institute is a cross-project master (``mas_mentor_institute``) attached to
district-level units (``map_mentor_institute_org_unit``) and staffed by users
(``map_mentor_institute_user``). Mentor access is through ordinary unit
grants; the maps only *guard* writing them: ``check_mentor_grant`` refuses a
member any grant outside an attached district's subtree or outside
``MENTOR_ROLES``. Detach and remove soft-deactivate (``is_active``), so they
are reversible and leave grants alone, except ``remove_staff`` (institute staff
API), which also deactivates the person's mentor grants inside the institute's
districts.

An institute admin (``map_mentor_institute_user.is_admin``) creates and
removes their own institute's staff only; they never give grants. Who may
write a member's grant is ``authz.can_grant`` (the district rule: a data
manager writes the mentor roles anywhere in their own subtree); the guard
still narrows it at write time.

Policy: docs/policy/organization-model.md, "Mentoring institutes".
Platform-admin management is enforced by the callers (``flask mentor-institute``);
staff management by the institute admin by ``require_institute_admin``.
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
from app.services.org_grant_service import active_project_condition
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
    the guard would now refuse (not unit scope, not a mentor role, or a unit
    outside every district their institutes are attached to); those stay in
    place until an admin revokes them.
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
                    _covered_by_institutes(user.user_id, VaUserAccessGrants.org_unit_id),
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


def set_member_admin(institute_code, email: str, is_admin: bool, *, actor_user_id=None) -> None:
    """Set or clear the institute-admin flag on an active member (platform admin only)."""
    institute = _institute(institute_code)
    user = _user_by_email(email)
    link = db.session.get(MapMentorInstituteUser, (institute.institute_id, user.user_id))
    if link is None or not link.is_active:
        raise OrganizationError("That user is not active staff of that institute; add them first.")
    link.is_admin = is_admin
    log_mentor_institute_action(
        action="mentor_admin_set" if is_admin else "mentor_admin_cleared",
        actor_user_id=actor_user_id,
        institute=institute.institute_code,
        target=user.user_id,
    )


# ---------------------------------------------------------------------------
# Institute admin: own-institute staff only, never grants (caller commits)
# ---------------------------------------------------------------------------


def administered_institutes(user_id) -> list[MasMentorInstitute]:
    """Active institutes the user administers (active admin link, active institute)."""
    return list(
        db.session.scalars(
            sa.select(MasMentorInstitute)
            .join(
                MapMentorInstituteUser,
                MapMentorInstituteUser.institute_id == MasMentorInstitute.institute_id,
            )
            .where(
                MapMentorInstituteUser.user_id == user_id,
                MapMentorInstituteUser.is_admin.is_(True),
                MapMentorInstituteUser.is_active.is_(True),
                MasMentorInstitute.is_active.is_(True),
            )
            .order_by(MasMentorInstitute.institute_code)
        ).all()
    )


def institute_for_staff_management(user, institute_code) -> MasMentorInstitute:
    """The institute whose staff *user* may manage: any for a platform admin,
    only their own otherwise. Raises OrganizationError (not found / not yours)."""
    if user.is_admin():
        return _institute(institute_code)
    return require_institute_admin(user.user_id, institute_code)


def require_institute_admin(user_id, institute_code) -> MasMentorInstitute:
    """The institute, if the user administers it; else OrganizationError.

    The same refusal for an unknown and for another institute's code, so an
    institute admin cannot probe which institutes exist.
    """
    try:
        code = normalize_code(institute_code, what="Institute code")
    except OrganizationError:
        code = None
    for institute in administered_institutes(user_id):
        if institute.institute_code == code:
            return institute
    raise OrganizationError("You do not administer that institute.")


def list_staff(institute: MasMentorInstitute) -> list[tuple[VaUsers, MapMentorInstituteUser]]:
    """Active staff of the institute, with their membership row."""
    return [
        (user, link)
        for user, link in db.session.execute(
            sa.select(VaUsers, MapMentorInstituteUser)
            .join(MapMentorInstituteUser, MapMentorInstituteUser.user_id == VaUsers.user_id)
            .where(
                MapMentorInstituteUser.institute_id == institute.institute_id,
                MapMentorInstituteUser.is_active.is_(True),
            )
            .order_by(VaUsers.email)
        )
    ]


def create_staff(institute: MasMentorInstitute, fields: dict, *, actor_user_id) -> VaUsers:
    """Create an invited account and make it staff of *institute*.

    *fields* come from ``user_account_service.validate_new_user_payload``. The
    account is tagged with the institute so ``remove_staff`` may later
    deactivate it. Refuses an inactive institute. The caller commits, then
    sends the invitation.
    """
    from app.services.user_account_service import create_invited_user

    if not institute.is_active:
        raise OrganizationError("That institute is inactive.")

    user = create_invited_user(
        fields,
        via="mentor_institute",
        actor_user_id=actor_user_id,
        other={
            "created_by_user_id": str(actor_user_id),
            "created_by_mentor_institute": institute.institute_code,
        },
    )
    db.session.add(
        MapMentorInstituteUser(
            institute_id=institute.institute_id,
            user_id=user.user_id,
            created_by_user_id=actor_user_id,
        )
    )
    db.session.flush()
    log_mentor_institute_action(
        action="mentor_staff_created",
        actor_user_id=actor_user_id,
        institute=institute.institute_code,
        target=user.user_id,
    )
    return user


def remove_staff(
    institute: MasMentorInstitute, user_id, *, actor_user_id, actor_is_platform_admin=False
) -> tuple[bool, int]:
    """Remove a person from *institute*'s staff; returns (account deactivated, grants deactivated).

    Membership is deactivated, and so are (never deleted) the person's active
    mentor-role unit grants inside this institute's attached district subtrees,
    except units another institute they remain staff of still covers. The
    account is deactivated only when this institute created it and the person
    belongs to no other active institute, so an institute never switches off
    someone who is also another body's staff or was not its own hire. Cannot
    remove oneself, and only a platform admin may remove an institute admin.
    """
    if user_id == actor_user_id:
        raise OrganizationError("You cannot remove yourself from your institute.")
    link = db.session.get(MapMentorInstituteUser, (institute.institute_id, user_id))
    if link is None or not link.is_active:
        raise OrganizationError("That user is not staff of your institute.")
    if link.is_admin and not actor_is_platform_admin:
        raise OrganizationError("Only a platform administrator can remove an institute admin.")
    link.is_active = False
    link.is_admin = False
    db.session.flush()  # so _covered_by_institutes sees only the remaining memberships
    grants_deactivated = _deactivate_institute_grants(institute, user_id)
    user = db.session.get(VaUsers, user_id)
    deactivated = False
    if (
        user is not None
        and (user.other or {}).get("created_by_mentor_institute") == institute.institute_code
        and user_id not in member_user_ids([user_id])
    ):
        user.user_status = VaStatuses.deactive
        deactivated = True
    db.session.flush()
    log_mentor_institute_action(
        action="mentor_staff_removed",
        actor_user_id=actor_user_id,
        institute=institute.institute_code,
        target=user_id,
        account_deactivated=deactivated,
        grants_deactivated=grants_deactivated,
    )
    return deactivated, grants_deactivated


def _deactivate_institute_grants(institute: MasMentorInstitute, user_id) -> int:
    """Deactivate the user's active mentor-role unit grants inside *institute*'s
    district subtrees (any attachment, active or not) that no remaining
    membership of theirs covers. Returns the count."""
    district = sa.orm.aliased(MasOrgUnit, name="removed_district")
    unit = sa.orm.aliased(MasOrgUnit, name="removed_unit")
    in_institute = (
        sa.select(sa.literal(1))
        .select_from(MapMentorInstituteOrgUnit)
        .join(district, district.org_unit_id == MapMentorInstituteOrgUnit.org_unit_id)
        .where(
            MapMentorInstituteOrgUnit.institute_id == institute.institute_id,
            district.project_id == unit.project_id,
            sa.text("removed_unit.path <@ removed_district.path"),
        )
        .exists()
    )
    grant_ids = (
        sa.select(VaUserAccessGrants.grant_id)
        .join(unit, unit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.role.in_(MENTOR_ROLES),
            in_institute,
            sa.not_(_covered_by_institutes(user_id, VaUserAccessGrants.org_unit_id)),
        )
    )
    return db.session.execute(
        sa.update(VaUserAccessGrants)
        .where(VaUserAccessGrants.grant_id.in_(grant_ids))
        .values(grant_status=VaStatuses.deactive)
        .execution_options(synchronize_session="fetch")
    ).rowcount


# ---------------------------------------------------------------------------
# District data manager reach (grants for members inside managed districts)
# ---------------------------------------------------------------------------


def dm_visible_mentor_staff(
    dm_user_id, query: str, include_inactive: bool, limit: int = 25, *, user_id=None
) -> tuple[list[tuple[VaUsers, list[str]]], bool]:
    """Active staff of active institutes attached to a district the data manager
    covers, with their institute codes: a project-scope data_manager grant in
    the district's project, or a unit data_manager grant at the district or above it.

    Backs the unit-only data manager's user search: nobody outside those
    institutes, and no inactive membership, is returned. The query is a literal
    substring (``%`` and ``_`` are escaped). *user_id* narrows the answer to
    that one person (is this account visible to the data manager?). Returns
    ``(rows, truncated)``; *truncated* is True when more than *limit* people
    matched.
    """
    district = sa.orm.aliased(MasOrgUnit, name="dm_search_district")
    granted = sa.orm.aliased(MasOrgUnit, name="dm_search_granted")
    covered = sa.or_(
        district.project_id.in_(_project_scope_dm_projects(dm_user_id)),
        sa.exists().where(
            VaUserAccessGrants.user_id == dm_user_id,
            VaUserAccessGrants.role == VaAccessRoles.data_manager,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            granted.org_unit_id == VaUserAccessGrants.org_unit_id,
            granted.is_active.is_(True),
            active_project_condition(granted.project_id),
            granted.project_id == district.project_id,
            sa.text("dm_search_district.path <@ dm_search_granted.path"),
        ),
    )
    codes = sa.func.array_agg(sa.distinct(MasMentorInstitute.institute_code))
    stmt = (
        sa.select(VaUsers, codes)
        .join(MapMentorInstituteUser, MapMentorInstituteUser.user_id == VaUsers.user_id)
        .join(
            MasMentorInstitute,
            MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
        )
        .join(
            MapMentorInstituteOrgUnit,
            MapMentorInstituteOrgUnit.institute_id == MasMentorInstitute.institute_id,
        )
        .join(district, district.org_unit_id == MapMentorInstituteOrgUnit.org_unit_id)
        .where(
            MapMentorInstituteUser.is_active.is_(True),
            MasMentorInstitute.is_active.is_(True),
            MapMentorInstituteOrgUnit.is_active.is_(True),
            district.is_active.is_(True),
            covered,
        )
        .group_by(VaUsers.user_id)
        .order_by(VaUsers.email)
        .limit(limit + 1)
    )
    if not include_inactive:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    if user_id is not None:
        stmt = stmt.where(VaUsers.user_id == user_id)
    if query:
        stmt = stmt.where(
            sa.or_(
                VaUsers.email.icontains(query, autoescape=True),
                VaUsers.name.icontains(query, autoescape=True),
            )
        )
    rows = [(user, sorted(c)) for user, c in db.session.execute(stmt)]
    return rows[:limit], len(rows) > limit


def _project_scope_dm_projects(user_id) -> set[str]:
    return set(
        db.session.scalars(
            sa.select(VaUserAccessGrants.project_id).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == VaAccessRoles.data_manager,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
                VaUserAccessGrants.grant_status == VaStatuses.active,
                active_project_condition(VaUserAccessGrants.project_id),
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# Guard and reads
# ---------------------------------------------------------------------------


def active_member_ids_select():
    """SELECT of the user ids that are active members of an active institute."""
    return (
        sa.select(MapMentorInstituteUser.user_id)
        .join(
            MasMentorInstitute,
            MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
        )
        .where(
            MapMentorInstituteUser.is_active.is_(True),
            MasMentorInstitute.is_active.is_(True),
        )
    )


def member_user_ids(user_ids) -> set[uuid.UUID]:
    """Which of *user_ids* are active members of an active institute (one query)."""
    user_ids = list(user_ids)
    if not user_ids:
        return set()
    return set(
        db.session.scalars(
            active_member_ids_select().where(MapMentorInstituteUser.user_id.in_(user_ids))
        ).all()
    )


def _covered_by_institutes(user_id, unit_id_expr):
    """EXISTS: *unit_id_expr* lies in a district attached to an institute the
    user is an active member of (all links, institutes, districts active).
    """
    district = sa.orm.aliased(MasOrgUnit, name="mentor_district")
    target = sa.orm.aliased(MasOrgUnit, name="mentored_unit")
    return (
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
            target.org_unit_id == unit_id_expr,
        )
        .exists()
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
    covered = db.session.scalar(sa.select(_covered_by_institutes(user_id, unit.org_unit_id)))
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
