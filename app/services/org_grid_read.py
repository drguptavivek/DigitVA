"""Project users grid read: one consolidated row per user, a single pass (digitva-r8nh.14).

Moved unchanged out of org_grid.py; org_grid re-exports these names.
"""

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
from app.services.org_cadres import (
    list_cadres,
    list_level_cadres,
    serialize_cadre,
)
from app.services.org_common import _get_project
from app.services.org_levels_units import (
    list_levels,
    list_units,
    serialize_level,
)

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
