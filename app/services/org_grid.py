"""Project users grid and the 2-dropdown bulk apply (digitva-dus.4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    AuthDevice,
    AuthDeviceSession,
    MapMentorInstituteUser,
    MapProjectMember,
    MasCadre,
    MasMentorInstitute,
    MasOrgLevel,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessScopeTypes,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.va_selectives import ROLE_LABELS
from app.services import authz
from app.services.org_cadres import (
    get_level_cadre_permission,
    list_cadres,
    list_level_cadres,
    serialize_cadre,
)
from app.services.org_common import (
    OrganizationError,
    _get_project,
    _uuid,
)
from app.services.org_grid_context import ApplyContext
from app.services.org_grid_ops import (  # noqa: F401  _Stage etc. stay importable from here
    _BULK_ROLE_MAP,
    OPERATIONS,
    _Operation,
    _Stage,
)
from app.services.org_levels_units import (
    _get_unit,
    list_levels,
    list_units,
    serialize_level,
)
from app.services.org_workers import (
    update_worker,
)


def replace_placement_grants(
    project_id: str,
    worker: MasOrgUnitWorker,
    *,
    old_unit_id: uuid.UUID,
    old_cadre_id: uuid.UUID,
    was_active: bool,
    actor: VaUsers,
) -> list[tuple[dict, str]]:
    """Make the linked person's unit roles follow a placement change
    (dm-user-grant-management.md, "Placement changes replace unit roles").

    Call after ``update_worker`` with the worker's pre-edit unit, cadre and
    active flag. When an active placement moves unit or cadre, or is
    deactivated, every active unit-scope grant the person holds at the OLD
    unit is set inactive (unless another active placement of the person is
    at that unit); a placement still active then gets the new
    level x cadre ``default_roles`` at its unit through the bulk
    ``cadre_defaults`` operation (``bulk_apply_project_users_grid``).
    Project, site and other-unit grants (cross-unit coding or supervision
    scope included) are untouched; reactivation restores nothing.

    All or nothing: raises OrganizationError, before the caller commits,
    when *actor* may not revoke one of the grants (``authz.grant_list_filter``)
    or grant a default role. A grant revoked and granted again (cadre change
    at one unit keeping a role) is left out of the result.

    Returns changed grants in ``project_user_import_service.finalize_apply``'s
    shape; empty when nothing placement-related changed or no account is linked.
    """
    moved = worker.org_unit_id != old_unit_id or worker.cadre_id != old_cadre_id
    if worker.user_id is None or not was_active or not (moved or not worker.is_active):
        return []
    G = VaUserAccessGrants
    # Another active placement of the person at the old unit keeps its roles.
    still_placed = db.session.scalar(
        sa.select(MasOrgUnitWorker.worker_id).where(
            MasOrgUnitWorker.project_id == project_id,
            MasOrgUnitWorker.user_id == worker.user_id,
            MasOrgUnitWorker.org_unit_id == old_unit_id,
            MasOrgUnitWorker.is_active.is_(True),
            MasOrgUnitWorker.worker_id != worker.worker_id,
        ).limit(1)
    )
    managed = sa.func.coalesce(authz.grant_list_filter(actor), sa.false())
    rows = [] if still_placed is not None else db.session.execute(
        sa.select(G, managed.label("managed")).where(
            G.user_id == worker.user_id,
            G.grant_status == VaStatuses.active,
            G.scope_type == VaAccessScopeTypes.org_unit,
            G.org_unit_id == old_unit_id,
        ).with_for_update(of=G)
    ).all()
    refused = sorted({g.role.value for g, ok in rows if not ok})
    if refused:
        raise OrganizationError(
            "You may not revoke this person's " + ", ".join(refused)
            + " role at their current unit; nothing was changed."
        )
    revoked: dict = {}
    for grant, _ in rows:
        grant.grant_status = VaStatuses.deactive
        revoked[grant.grant_id] = (dict(
            user_id=grant.user_id, grant_id=grant.grant_id, role=grant.role.value,
            scope_type=grant.scope_type.value, org_unit_id=grant.org_unit_id, cadre_id=grant.cadre_id,
        ), "grant_toggled_inactive")
    db.session.flush()
    granted: list[tuple[dict, str]] = []
    person = db.session.get(VaUsers, worker.user_id)
    if worker.is_active and person is not None and person.user_status == VaStatuses.active:
        # The loaded ``worker.unit`` may still be the old unit after a move.
        permission = get_level_cadre_permission(_get_unit(project_id, worker.org_unit_id).org_level_id, worker.cadre_id)
        if permission is not None and permission.default_roles:
            _, granted = bulk_apply_project_users_grid(
                project_id,
                {"user_ids": [str(worker.user_id)], "operation": "cadre_defaults", "scope_mode": "project",
                 "worker_id": worker.worker_id},
                actor=actor,
            )
    regranted = {g["grant_id"] for g, _ in granted} & set(revoked)
    return [revoked[k] for k in revoked if k not in regranted] + [
        c for c in granted if c[0]["grant_id"] not in regranted
    ]


_DISPLAY_ROLE_META: dict[str, dict[str, object]] = {
    "project_pi": {
        "label": "Project PI",
        "pii_badge": "Tier 1: Non-PII",
        "pii_tier": "non_pii",
        "with_pii": False,
        "order": 1,
    },
    "site_pi": {
        "label": "In-charge",
        "pii_badge": "Tier 3: PII",
        "pii_tier": "full_pii",
        "with_pii": True,
        "order": 2,
    },
    "data_manager": {
        "label": "Data Manager",
        "pii_badge": "Tier 3: PII",
        "pii_tier": "full_pii",
        "with_pii": True,
        "order": 3,
    },
    "coder_non_pii": {
        "label": "Coder",
        "pii_badge": "Tier 1/2: Non-PII",
        "pii_tier": "non_pii",
        "with_pii": False,
        "order": 4,
    },
    "coder_pii": {
        "label": "Coder",
        "pii_badge": "Tier 3: PII",
        "pii_tier": "coding_pii",
        "with_pii": True,
        "order": 5,
    },
    "reviewer_non_pii": {
        "label": "Reviewer",
        "pii_badge": "Tier 1/2: Non-PII",
        "pii_tier": "non_pii",
        "with_pii": False,
        "order": 6,
    },
    "reviewer_pii": {
        "label": "Reviewer",
        "pii_badge": "Tier 3: PII",
        "pii_tier": "coding_pii",
        "with_pii": True,
        "order": 7,
    },
    "coding_tester": {
        "label": "Coding Tester",
        "pii_badge": "Non-PII",
        "pii_tier": "non_pii",
        "with_pii": False,
        "order": 8,
    },
    "interviewer": {
        "label": "Interviewer",
        "pii_badge": "Tier 3: PII",
        "pii_tier": "full_pii",
        "with_pii": True,
        "order": 9,
    },
    "interview_supervisor": {
        "label": "Interview Supervisor",
        "pii_badge": "Tier 3: PII",
        "pii_tier": "intake_pii",
        "with_pii": True,
        "order": 10,
    },
    "death_reporter": {
        "label": "Death Reporter",
        "pii_badge": "Own Register",
        "pii_tier": "own_register",
        "with_pii": True,
        "order": 11,
    },
    "collaborator_pii": {
        "label": "Viewer (with PII)",
        "pii_badge": "PII",
        "pii_tier": "full_pii",
        "with_pii": True,
        "order": 12,
    },
    "collaborator": {
        "label": "Viewer (Non-PII)",
        "pii_badge": "Tier 1/2: Non-PII",
        "pii_tier": "non_pii",
        "with_pii": False,
        "order": 13,
    },
}


def _grant_in_project(project_id: str) -> sa.ColumnElement:
    """SQL over ``VaUserAccessGrants``: a grant in *project_id* at project,
    project-site or unit scope (any unit of the project, active or not)."""
    G = VaUserAccessGrants
    return sa.or_(
        sa.and_(G.scope_type == VaAccessScopeTypes.project, G.project_id == project_id),
        sa.and_(G.scope_type == VaAccessScopeTypes.project_site, G.project_site_id.in_(
            sa.select(VaProjectSites.project_site_id).where(VaProjectSites.project_id == project_id)
        )),
        sa.and_(G.scope_type == VaAccessScopeTypes.org_unit, G.org_unit_id.in_(
            sa.select(MasOrgUnit.org_unit_id).where(MasOrgUnit.project_id == project_id)
        )),
    )


def on_project_roster(project_id: str, user_id_col) -> sa.ColumnElement:
    """SQL predicate: the account *user_id_col* is already on *project_id*'s
    People roster -- a member of it, holding an active grant in it (project,
    one of its pairs, or one of its units), or a worker in it.

    A non-admin roster write (bulk-apply, Place, move) and a roster sign-in
    code target only such an account, so a PI or data manager cannot grant a
    role to an arbitrary account and then take it over with a code
    (docs/policy/access-control-model.md, "Project membership")."""
    G = VaUserAccessGrants
    return sa.or_(
        sa.exists().where(MapProjectMember.user_id == user_id_col, MapProjectMember.project_id == project_id),
        sa.exists().where(G.user_id == user_id_col, G.grant_status == VaStatuses.active, _grant_in_project(project_id)),
        sa.exists().where(MasOrgUnitWorker.user_id == user_id_col, MasOrgUnitWorker.project_id == project_id),
    )


def require_on_project_roster(project_id: str, user_ids, *, actor) -> None:
    """Raise OrganizationError unless every one of *user_ids* is on
    *project_id*'s roster (``on_project_roster``); one query. Admins pass.
    The refusal names no account, as for an unknown id."""
    ids = {uuid.UUID(str(u)) for u in user_ids}
    if not ids or authz.resolve_grants(actor).is_admin:
        return
    found = db.session.scalar(
        sa.select(sa.func.count()).select_from(VaUsers)
        .where(VaUsers.user_id.in_(ids), on_project_roster(project_id, VaUsers.user_id))
    )
    if found != len(ids):
        raise OrganizationError("One or more selected users were not found.")


def remove_from_project(project_id: str, user: VaUsers, *, actor) -> tuple[dict, list]:
    """Take *user* off *project_id*: every active grant they hold in it
    (project, site and unit scope) set inactive, their active workers in it
    set inactive (``update_worker``) and their membership row deleted, with
    one ``removed_from_project`` security event (project id, counts, and who
    added the membership and when, as the row has no status column).

    All or nothing: when *actor* may not revoke one of the grants
    (``authz.grant_list_filter``, the rule of ``authz.can_grant`` over the
    table), raises OrganizationError naming those roles and changes nothing.
    The caller refuses oneself and, for a non-admin, an admin account, and
    commits; the grants are ORM rows, so the commit queues the person's
    ``access_changed`` notice. The account, its password, phones, other
    projects, submissions and death reports are untouched.
    Policy: dm-user-grant-management.md, "Roster User Panel".

    Returns ``(detail, changed_grants)``: the event detail, and the revoked
    grants in ``project_user_import_service.finalize_apply``'s shape.
    """
    from app.services.security_event_service import record_security_event

    G = VaUserAccessGrants
    managed = sa.func.coalesce(authz.grant_list_filter(actor), sa.false())
    rows = db.session.execute(
        sa.select(G, managed.label("managed")).where(
            G.user_id == user.user_id, G.grant_status == VaStatuses.active, _grant_in_project(project_id),
        ).with_for_update(of=G)
    ).all()
    refused = sorted({g.role.value for g, ok in rows if not ok})
    if refused:
        raise OrganizationError(
            "You may not remove this person's " + ", ".join(refused)
            + " access here; nothing was changed."
        )
    changed = []
    for grant, _ in rows:
        grant.grant_status = VaStatuses.deactive
        changed.append((dict(
            user_id=grant.user_id, grant_id=grant.grant_id, role=grant.role.value,
            scope_type=grant.scope_type.value, org_unit_id=grant.org_unit_id, cadre_id=grant.cadre_id,
        ), "grant_toggled_inactive"))
    workers = db.session.scalars(
        sa.select(MasOrgUnitWorker).where(
            MasOrgUnitWorker.user_id == user.user_id,
            MasOrgUnitWorker.project_id == project_id,
            MasOrgUnitWorker.is_active.is_(True),
        )
    ).all()
    for worker in workers:
        update_worker(project_id, worker.worker_id, is_active=False)
    member = db.session.scalar(
        sa.select(MapProjectMember).where(
            MapProjectMember.project_id == project_id, MapProjectMember.user_id == user.user_id,
        )
    )
    detail = {
        "project_id": project_id,
        "grants_revoked": len(changed),
        "workers_deactivated": len(workers),
        "membership_removed": member is not None,
        "member_added_by_user_id": str(member.added_by_user_id) if member and member.added_by_user_id else None,
        "member_added_at": member.added_at.isoformat() if member else None,
    }
    if member is not None:
        db.session.delete(member)
    record_security_event(
        user_id=user.user_id, actor_user_id=actor.user_id, event_type="removed_from_project", detail=detail,
    )
    db.session.flush()
    return detail, changed


def get_project_users_grid(project_id: str, viewer: VaUsers | None = None) -> dict:
    """Return a consolidated 1-row-per-user roster for *project_id* with zero N+1 queries.

    Merges ``VaUsers``, ``MasOrgUnitWorker``, ``MapProjectMember`` (roster members
    with no grant yet), project/site ``VaUserAccessGrants``,
    and unit-scoped ``VaUserAccessGrants`` (combining ``coder`` + ``collaborator_pii``
    on the same unit into ``coder_pii`` vs ``coder_non_pii``, and similarly for
    ``reviewer_pii`` vs ``reviewer_non_pii``).

    Each row also carries its enrolment status (``activated``: the person
    knows a working password, ``has_usable_password``; ``phone_count``: live
    device sessions on non-revoked devices, any project; ``last_sign_in_at``)
    and ``can_issue_code``: *viewer* may issue a sign-in code for it from this
    roster (``mobile_sign_in_service.issuable_user_ids``: for a non-admin,
    never someone with a live phone, who needs no code), the account is
    active and has an email or mobile number to redeem with. Without a
    *viewer* it is False for every row. One query each, for all rows.
    """
    from app.services.mobile_sign_in_service import issuable_user_ids
    from app.services.user_account_service import has_usable_password
    project = _get_project(project_id)
    levels = [serialize_level(lv) for lv in list_levels(project_id, include_inactive=False)]
    units = list_units(project_id, include_inactive=False)
    cadres = [serialize_cadre(c) for c in list_cadres(project_id, include_inactive=False)]
    level_cadres = list_level_cadres(project_id)

    units_by_id: dict[str, dict] = {u["org_unit_id"]: u for u in units}
    units_by_level: dict[str, list[dict]] = {}
    for u in units:
        units_by_level.setdefault(u["org_level_id"], []).append(u)

    default_roles_by_pair: dict[tuple[str, str], list[str]] = {
        (lc["org_level_id"], lc["cadre_id"]): list(lc.get("default_roles") or [])
        for lc in level_cadres
        if lc.get("is_active", True)
    }

    # Project sites
    ps_rows = db.session.execute(
        sa.select(VaProjectSites, VaSiteMaster)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(VaProjectSites.project_id == project_id)
        .order_by(VaProjectSites.site_id)
    ).all()
    sites_list = [
        {
            "project_site_id": str(ps.project_site_id),
            "site_id": ps.site_id,
            "site_name": sm.site_name,
            "project_site_status": ps.project_site_status.value if hasattr(ps.project_site_status, "value") else str(ps.project_site_status),
            "coding_enabled": bool(ps.coding_enabled),
            "coding_start_date": ps.coding_start_date.isoformat() if ps.coding_start_date else None,
            "coding_end_date": ps.coding_end_date.isoformat() if ps.coding_end_date else None,
            "daily_coder_limit": ps.daily_coder_limit,
            "collection_enabled": bool(ps.collection_enabled),
            "collection_start_date": ps.collection_start_date.isoformat() if ps.collection_start_date else None,
            "collection_end_date": ps.collection_end_date.isoformat() if ps.collection_end_date else None,
            "daily_interviewer_limit": ps.daily_interviewer_limit,
        }
        for ps, sm in ps_rows
    ]
    ps_by_id = {s["project_site_id"]: s for s in sites_list}
    ps_uuids = [ps.project_site_id for ps, _ in ps_rows]

    all_unit_rows = db.session.scalars(
        sa.select(MasOrgUnit).where(MasOrgUnit.project_id == project_id).order_by(MasOrgUnit.path)
    ).all()
    all_unit_uuids = [u.org_unit_id for u in all_unit_rows]
    all_units_by_uuid = {u.org_unit_id: u for u in all_unit_rows}

    # Workers in this project
    worker_rows = db.session.execute(
        sa.select(MasOrgUnitWorker, MasOrgUnit, MasOrgLevel, MasCadre)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .join(MasCadre, MasCadre.cadre_id == MasOrgUnitWorker.cadre_id)
        .where(MasOrgUnitWorker.project_id == project_id)
        .order_by(MasOrgUnitWorker.is_active.desc(), MasOrgUnit.path, MasOrgUnitWorker.worker_code)
    ).all()

    workers_by_user: dict[uuid.UUID, list[dict]] = {}
    unlinked_workers: list[dict] = []
    for w, u, lv, c in worker_rows:
        w_dict = {
            "worker_id": str(w.worker_id),
            "worker_code": w.worker_code,
            "worker_name": w.worker_name,
            "phone": w.phone,
            "org_unit_id": str(u.org_unit_id),
            "unit_code": u.unit_code,
            "unit_name": u.unit_name,
            "org_level_id": str(lv.org_level_id),
            "level_code": lv.level_code,
            "level_name": lv.level_name,
            "cadre_id": str(c.cadre_id),
            "cadre_code": c.cadre_code,
            "cadre_name": c.cadre_name,
            "default_roles": default_roles_by_pair.get((str(lv.org_level_id), str(c.cadre_id)), []),
            "is_active": bool(w.is_active),
        }
        if w.user_id is not None:
            workers_by_user.setdefault(w.user_id, []).append(w_dict)
        else:
            unlinked_workers.append(w_dict)

    # Grants in this project (project, project_site, org_unit)
    grant_conds = [
        sa.and_(
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id == project_id,
        )
    ]
    if ps_uuids:
        grant_conds.append(
            sa.and_(
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                VaUserAccessGrants.project_site_id.in_(ps_uuids),
            )
        )
    if all_unit_uuids:
        grant_conds.append(
            sa.and_(
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                VaUserAccessGrants.org_unit_id.in_(all_unit_uuids),
            )
        )

    grant_rows = db.session.scalars(
        sa.select(VaUserAccessGrants).where(sa.or_(*grant_conds))
    ).all()

    grants_by_user: dict[uuid.UUID, list[VaUserAccessGrants]] = {}
    for g in grant_rows:
        grants_by_user.setdefault(g.user_id, []).append(g)

    # Roster members (digitva-plgm) with no grant or worker yet still get a
    # row, "Not placed in a unit" with no active grants; membership grants nothing.
    member_user_ids = set(db.session.scalars(
        sa.select(MapProjectMember.user_id).where(MapProjectMember.project_id == project_id)
    ).all())
    all_user_ids = set(workers_by_user.keys()) | set(grants_by_user.keys()) | member_user_ids
    users_by_id: dict[uuid.UUID, VaUsers] = {}
    mentor_user_ids: set[uuid.UUID] = set()
    if all_user_ids:
        for u_obj in db.session.scalars(
            sa.select(VaUsers).where(VaUsers.user_id.in_(all_user_ids))
        ).all():
            users_by_id[u_obj.user_id] = u_obj
        mentor_user_ids = set(
            db.session.scalars(
                sa.select(MapMentorInstituteUser.user_id)
                .join(
                    MasMentorInstitute,
                    MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
                )
                .where(
                    MapMentorInstituteUser.user_id.in_(all_user_ids),
                    MapMentorInstituteUser.is_active.is_(True),
                    MasMentorInstitute.is_active.is_(True),
                )
            ).all()
        )

    phone_counts: dict[uuid.UUID, int] = {}
    issuable: set[uuid.UUID] = set()
    if all_user_ids:
        from app.services.device_auth_service import live_session_clauses

        phone_counts = dict(db.session.execute(
            sa.select(AuthDeviceSession.user_id, sa.func.count(sa.distinct(AuthDeviceSession.device_id)))
            .join(AuthDevice, AuthDevice.device_id == AuthDeviceSession.device_id)
            .where(AuthDeviceSession.user_id.in_(all_user_ids), *live_session_clauses(datetime.now(UTC)))
            .group_by(AuthDeviceSession.user_id)
        ).all())
        if viewer is not None:
            issuable = issuable_user_ids(viewer, project_id, all_user_ids)

    has_tree = bool(units)

    sorted_users = sorted(
        users_by_id.values(),
        key=lambda u: ((u.name or u.email or "").lower(), str(u.user_id)),
    )

    users_out: list[dict] = []
    counts = {
        "total_users": 0,
        "active_users": 0,
        "inactive_users": 0,
        "with_pii": 0,
        "non_pii_only": 0,
        "multi_unit_users": 0,
        "unlinked_workers": len(unlinked_workers),
    }

    for u_obj in sorted_users:
        uid = u_obj.user_id
        uid_str = str(uid)
        is_mentor = uid in mentor_user_ids
        u_workers = workers_by_user.get(uid, [])
        primary_worker = next((w for w in u_workers if w["is_active"]), u_workers[0] if u_workers else None)
        home_unit_id = primary_worker["org_unit_id"] if primary_worker else None
        home_level_id = primary_worker["org_level_id"] if primary_worker else None

        u_grants = grants_by_user.get(uid, [])
        active_grants = [g for g in u_grants if g.grant_status == VaStatuses.active]
        inactive_grant_count = sum(1 for g in u_grants if g.grant_status != VaStatuses.active)

        # Project & site grants (Tier 1 / Tier 2 on tree projects -> Non-PII)
        proj_roles_held: set[str] = set()
        proj_grants_out: list[dict] = []
        for g in active_grants:
            if g.scope_type in (VaAccessScopeTypes.project, VaAccessScopeTypes.project_site):
                r_val = g.role.value if hasattr(g.role, "value") else str(g.role)
                proj_roles_held.add(r_val)
                site_info = ps_by_id.get(str(g.project_site_id)) if g.project_site_id else None
                meta = _DISPLAY_ROLE_META.get(
                    "coder_non_pii" if r_val == "coder" else ("reviewer_non_pii" if r_val == "reviewer" else r_val),
                    {"label": ROLE_LABELS.get(g.role, r_val), "pii_badge": "Tier 1: Non-PII", "pii_tier": "non_pii", "with_pii": False},
                )
                label = str(meta["label"])
                pii_badge = str(meta["pii_badge"])
                with_pii = bool(meta["with_pii"])
                if has_tree and r_val != "admin":
                    with_pii = False
                    if r_val == "site_pi":
                        label = "Site Lead"
                        pii_badge = "Tier 2: Non-PII"
                    elif r_val == "data_manager":
                        label = "Project Data Manager"
                        pii_badge = "Tier 1: Non-PII"
                    elif r_val == "project_pi":
                        label = "Project PI"
                        pii_badge = "Tier 1: Non-PII"
                    else:
                        pii_badge = "Tier 1: Non-PII"
                elif not has_tree and not is_mentor and r_val in ("project_pi", "site_pi", "data_manager", "interviewer", "coder", "reviewer", "collaborator_pii"):
                    with_pii = True
                    pii_badge = "PII"
                elif is_mentor:
                    with_pii = False
                    pii_badge = "Tier 2: Non-PII"
                proj_grants_out.append({
                    "grant_id": str(g.grant_id),
                    "role": r_val,
                    "label": label,
                    "pii_badge": pii_badge,
                    "with_pii": with_pii,
                    "scope_type": g.scope_type.value,
                    "site_id": site_info["site_id"] if site_info else None,
                    "site_name": site_info["site_name"] if site_info else None,
                })

        has_project_wide_pii = (
            not has_tree
            and not is_mentor
            and bool(proj_roles_held & {"project_pi", "site_pi", "data_manager", "interviewer", "collaborator_pii"})
        )

        # Unit grants grouped by unit first
        roles_by_unit: dict[str, set[str]] = {}
        grant_ids_by_unit_role: dict[tuple[str, str], str] = {}
        for g in active_grants:
            if g.scope_type == VaAccessScopeTypes.org_unit and g.org_unit_id is not None:
                u_str = str(g.org_unit_id)
                if u_str not in units_by_id:
                    continue
                r_val = g.role.value if hasattr(g.role, "value") else str(g.role)
                roles_by_unit.setdefault(u_str, set()).add(r_val)
                grant_ids_by_unit_role[(u_str, r_val)] = str(g.grant_id)

        # Convert unit -> raw roles into display role -> list of units
        # Tier 3 (non-mentor-institute unit holders) see PII; Tier 2 (mentor institute) are Non-PII.
        units_by_display_role: dict[str, list[dict]] = {}
        raw_unit_roles_all: set[str] = set()
        for u_str, r_set in roles_by_unit.items():
            raw_unit_roles_all |= r_set
            u_info = units_by_id[u_str]
            unit_has_pii = (not is_mentor) or ("data_manager" in r_set) or has_project_wide_pii
            consumed_collab_pii = False

            display_keys: list[str] = []
            if "coder" in r_set:
                if unit_has_pii:
                    display_keys.append("coder_pii")
                    if "collaborator_pii" in r_set:
                        consumed_collab_pii = True
                else:
                    display_keys.append("coder_non_pii")
            if "reviewer" in r_set:
                if unit_has_pii:
                    display_keys.append("reviewer_pii")
                    if "collaborator_pii" in r_set:
                        consumed_collab_pii = True
                else:
                    display_keys.append("reviewer_non_pii")

            for r_val in sorted(r_set):
                if r_val in ("coder", "reviewer"):
                    continue
                if r_val == "collaborator_pii" and consumed_collab_pii:
                    continue
                display_keys.append(r_val)

            for dk in display_keys:
                units_by_display_role.setdefault(dk, []).append({
                    "org_unit_id": u_str,
                    "unit_code": u_info["unit_code"],
                    "unit_name": u_info["unit_name"],
                    "org_level_id": u_info["org_level_id"],
                    "level_code": u_info["level_code"],
                    "level_name": u_info["level_name"],
                    "depth": u_info["depth"],
                    "is_home": u_str == home_unit_id,
                })

        grouped_unit_roles: list[dict] = []
        distinct_granted_units = set(roles_by_unit.keys())
        for dk, dk_units in sorted(
            units_by_display_role.items(),
            key=lambda kv: int(_DISPLAY_ROLE_META.get(kv[0], {}).get("order", 99)),
        ):
            dk_units.sort(key=lambda x: (not x["is_home"], x["depth"], x["unit_code"]))
            meta = _DISPLAY_ROLE_META.get(
                dk,
                {"label": dk, "pii_badge": "Non-PII", "pii_tier": "non_pii", "with_pii": False},
            )
            u_ids_set = {x["org_unit_id"] for x in dk_units}
            levels_in_group = {x["org_level_id"] for x in dk_units}
            scope_kind = "multi"
            scope_summary = f"{len(dk_units)} units"

            if len(dk_units) == 1 and dk_units[0]["is_home"]:
                scope_kind = "own"
                scope_summary = f"Own unit ({dk_units[0]['unit_code']})"
            elif len(levels_in_group) == 1:
                only_lv = next(iter(levels_in_group))
                lv_all = {x["org_unit_id"] for x in units_by_level.get(only_lv, [])}
                lv_name = dk_units[0]["level_name"]
                if len(lv_all) >= 2 and u_ids_set == lv_all:
                    scope_kind = "all_level"
                    scope_summary = f"All {len(dk_units)} {lv_name} units"
                elif (
                    home_unit_id
                    and home_level_id == only_lv
                    and len(lv_all) >= 2
                    and u_ids_set == (lv_all - {home_unit_id})
                ):
                    scope_kind = "cross_level"
                    scope_summary = f"Cross-tree: All {len(dk_units)} other {lv_name} units"
                elif len(dk_units) == 1:
                    scope_kind = "single"
                    scope_summary = f"{dk_units[0]['unit_code']} ({dk_units[0]['unit_name']})"
            elif len(dk_units) == 1:
                scope_kind = "single"
                scope_summary = f"{dk_units[0]['unit_code']} ({dk_units[0]['unit_name']})"

            grouped_unit_roles.append({
                "role_key": dk,
                "label": str(meta["label"]),
                "pii_badge": str(meta["pii_badge"]),
                "pii_tier": str(meta["pii_tier"]),
                "with_pii": bool(meta["with_pii"]),
                "units": dk_units,
                "unit_count": len(dk_units),
                "scope_kind": scope_kind,
                "scope_summary": scope_summary,
            })

        # Compute effective PII status across the project for this user
        all_roles_held = proj_roles_held | raw_unit_roles_all
        display_keys_held = set(units_by_display_role.keys())
        in_system_unit_roles = raw_unit_roles_all if not is_mentor else (raw_unit_roles_all & {"data_manager"})
        if not all_roles_held:
            pii_status = {
                "tier": "none",
                "badge": "No Active Grants",
                "detail": "Rostered or inactive grants only; cannot access project cases.",
            }
        elif (
            bool(in_system_unit_roles & {"site_pi", "data_manager", "interviewer", "collaborator_pii"})
            or (not has_tree and not is_mentor and bool(proj_roles_held & {"project_pi", "site_pi", "data_manager", "interviewer", "collaborator_pii"}))
        ):
            pii_status = {
                "tier": "full_pii",
                "badge": "Tier 3: PII (In-System)",
                "detail": "Inside the health system: sees deceased name, address, GPS & registration numbers in scope.",
            }
        elif ("coder_pii" in display_keys_held) or ("reviewer_pii" in display_keys_held) or (
            not has_tree and not is_mentor and bool(proj_roles_held & {"coder", "reviewer"})
        ):
            pii_status = {
                "tier": "coding_pii",
                "badge": "Tier 3: PII (In-System Doctor)",
                "detail": "Inside the health system: sees deceased name & registration numbers across coding scope.",
            }
        elif "interview_supervisor" in in_system_unit_roles:
            pii_status = {
                "tier": "intake_pii",
                "badge": "Tier 3: PII (Supervisor)",
                "detail": "Inside the health system: sees deceased & respondent PII across supervised units.",
            }
        elif "death_reporter" in all_roles_held and not (
            all_roles_held - {"death_reporter"}
        ):
            pii_status = {
                "tier": "own_register",
                "badge": "Own Register PII",
                "detail": "Sees PII only on deaths registered by this worker.",
            }
        else:
            pii_status = {
                "tier": "non_pii",
                "badge": "Tier 2: Non-PII (Mentoring)" if is_mentor else "Tier 1: Non-PII (Blinded)",
                "detail": "Outside the health system: blinded to deceased name, address, GPS & registration numbers.",
            }

        is_user_active = u_obj.user_status == VaStatuses.active
        counts["total_users"] += 1
        if is_user_active:
            counts["active_users"] += 1
        else:
            counts["inactive_users"] += 1
        if pii_status["tier"] in ("full_pii", "coding_pii", "intake_pii", "own_register"):
            counts["with_pii"] += 1
        elif pii_status["tier"] == "non_pii":
            counts["non_pii_only"] += 1
        if len(distinct_granted_units) > 1:
            counts["multi_unit_users"] += 1

        users_out.append({
            "row_id": uid_str,
            "user_id": uid_str,
            "has_account": True,
            "name": u_obj.name or (primary_worker["worker_name"] if primary_worker else "") or (u_obj.email or "Unnamed"),
            "email": u_obj.email,
            "email_verified": bool(getattr(u_obj, "email_verified", True)),
            "mobile_only": bool(getattr(u_obj, "is_mobile_only", False)),
            "phone": u_obj.phone or u_obj.mobile_login or (primary_worker["phone"] if primary_worker else None),
            "user_status": u_obj.user_status.value if hasattr(u_obj.user_status, "value") else str(u_obj.user_status),
            "is_active": is_user_active,
            "is_mentor": is_mentor,
            # Stored naive UTC (va_users.user_created_at); sent with its offset so
            # the grid filters on the viewer's local date.
            "user_created_at": (
                u_obj.user_created_at.replace(tzinfo=UTC).isoformat()
                if u_obj.user_created_at and u_obj.user_created_at.tzinfo is None
                else (u_obj.user_created_at.isoformat() if u_obj.user_created_at else None)
            ),
            "activated": has_usable_password(u_obj),
            "phone_count": phone_counts.get(uid, 0),
            "last_sign_in_at": u_obj.last_signed_in_at.isoformat() if u_obj.last_signed_in_at else None,
            "can_issue_code": (
                uid in issuable and is_user_active
                and (u_obj.email is not None or u_obj.mobile_login is not None)
            ),
            "primary_worker": primary_worker,
            "workers": u_workers,
            "project_grants": proj_grants_out,
            "grouped_unit_roles": grouped_unit_roles,
            "unit_roles_by_unit": {k: sorted(v) for k, v in roles_by_unit.items()},
            # One entry per active unit grant, for the drawer's list and its remove buttons.
            "unit_grants": [
                {"grant_id": gid, "org_unit_id": u_str, "role": r_val}
                for (u_str, r_val), gid in sorted(grant_ids_by_unit_role.items())
            ],
            "active_grant_count": len(active_grants),
            "inactive_grant_count": inactive_grant_count,
            "distinct_unit_count": len(distinct_granted_units),
            "pii_status": pii_status,
        })

    return {
        "project_id": project_id,
        "structure_mode": project.project_structure_mode,
        "levels": levels,
        "units": units,
        "cadres": cadres,
        "level_cadres": level_cadres,
        "sites": sites_list,
        "users": users_out,
        "unlinked_workers": unlinked_workers,
        "counts": counts,
    }


def bulk_apply_project_users_grid(
    project_id: str,
    payload: dict,
    *,
    actor: VaUsers,
) -> tuple[dict, list[tuple[dict, str]]]:
    """Apply a 2-dropdown bulk role/scope/status operation to selected project users.

    Automatically resolves each user's home cadre (or an active capable cadre at
    the target unit's level) so the operator never needs a 3rd Cadre dropdown.
    A non-admin *actor* is refused, before any write, when a selected user is
    not on the project's roster (``require_on_project_roster``).
    """
    project = _get_project(project_id)
    raw_user_ids = payload.get("user_ids") or []
    if not isinstance(raw_user_ids, list) or not raw_user_ids:
        raise OrganizationError("Select at least one user first.")
    if len(raw_user_ids) > 500:
        raise OrganizationError("At most 500 users can be updated in one batch.")

    target_user_uuids: list[uuid.UUID] = []
    for raw_uid in raw_user_ids:
        uid = _uuid(raw_uid, what="User id")
        if uid not in target_user_uuids:
            target_user_uuids.append(uid)

    users_map = {
        u.user_id: u
        for u in db.session.scalars(
            sa.select(VaUsers).where(VaUsers.user_id.in_(target_user_uuids))
        ).all()
    }
    if len(users_map) != len(target_user_uuids):
        raise OrganizationError("One or more selected users were not found.")
    # A non-admin writes grants only for people already on this roster.
    require_on_project_roster(project_id, target_user_uuids, actor=actor)

    operation = str(payload.get("operation") or "").strip()
    scope_mode = str(payload.get("scope_mode") or "own").strip()
    sync_scope = bool(payload.get("sync_scope", True))

    if not operation:
        raise OrganizationError("Choose a role or action to apply.")

    ctx = ApplyContext(
        project=project,
        project_id=project_id,
        actor=actor,
        operation=operation,
        scope_mode=scope_mode,
        sync_scope=sync_scope,
        payload=payload,
        target_user_uuids=target_user_uuids,
        users_map=users_map,
        summary={
            "operation": operation,
            "scope_mode": scope_mode,
            "users_processed": len(target_user_uuids),
            "grants_created": 0,
            "grants_reactivated": 0,
            "grants_revoked": 0,
            "accounts_updated": 0,
        },
    )

    # An unknown operation walks every stage, then is refused where a handler would run.
    op = OPERATIONS.get(operation)
    stage = op.stage if op else _Stage.GRANT
    if stage > _Stage.ACCOUNT:
        ctx.load()
    if stage > _Stage.UNSCOPED:
        ctx.validate_scope()
    if stage >= _Stage.GRANT:
        for uid in target_user_uuids:
            if users_map[uid].user_status != VaStatuses.active:
                raise OrganizationError("DigitVA user is inactive.")
    if op is None:
        raise OrganizationError(f"Unknown bulk operation {operation!r}.")
    op.handler(ctx)
    db.session.flush()
    return ctx.summary, ctx.changed_grants
