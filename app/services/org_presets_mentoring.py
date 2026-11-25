"""Unit VA mortality presets and the project mentoring-institutes overview."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgUnitVaPresets,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import authz
from app.services.org_common import (
    OrganizationError,
    _get_project,
    _uuid,
)
from app.services.org_levels_units import (
    _get_unit,
    list_levels,
    list_units,
)

VA_PRESET_VALUES = ("high", "low", "veryl")


def serialize_unit_va_presets(presets: MapOrgUnitVaPresets | None) -> dict | None:
    if presets is None:
        return None
    return {
        "org_unit_id": str(presets.org_unit_id),
        "hiv_mortality": presets.hiv_mortality,
        "malaria_mortality": presets.malaria_mortality,
        "updated_at": presets.updated_at.isoformat() if presets.updated_at else None,
    }


def get_unit_va_presets(project_id: str, org_unit_id: object) -> MapOrgUnitVaPresets | None:
    """Return this unit's own VA presets row, or None -- absence means inherited.

    This is the unit's own row only, not the resolved (nearest-ancestor)
    value that actually prefills a draft -- see
    ``app.services.org_grant_service.resolve_unit_va_presets`` for that.
    """
    unit = _get_unit(project_id, org_unit_id)
    return db.session.get(MapOrgUnitVaPresets, unit.org_unit_id)


def _validate_va_preset_value(raw: object, *, what: str) -> str | None:
    if raw is None or raw == "":
        return None
    value = str(raw)
    if value not in VA_PRESET_VALUES:
        raise OrganizationError(f"{what} must be one of {', '.join(VA_PRESET_VALUES)}, or empty (not set).")
    return value


def set_unit_va_presets(
    project_id: str,
    org_unit_id: object,
    *,
    hiv_mortality: object,
    malaria_mortality: object,
    actor_id=None,
) -> MapOrgUnitVaPresets:
    """Create or update this unit's own HIV/malaria mortality presets.

    Either field left empty/None clears that preset on this unit -- it then
    inherits its nearest ancestor's value, if any, same as a unit that never
    set one.
    """
    unit = _get_unit(project_id, org_unit_id)
    hiv = _validate_va_preset_value(hiv_mortality, what="hiv_mortality")
    malaria = _validate_va_preset_value(malaria_mortality, what="malaria_mortality")

    presets = db.session.get(MapOrgUnitVaPresets, unit.org_unit_id)
    if presets is None:
        presets = MapOrgUnitVaPresets(org_unit_id=unit.org_unit_id)
        db.session.add(presets)
    presets.hiv_mortality = hiv
    presets.malaria_mortality = malaria
    presets.updated_by_user_id = actor_id
    db.session.flush()
    return presets


def clear_unit_va_presets(project_id: str, org_unit_id: object) -> bool:
    """Delete this unit's own VA presets row, if any. Returns whether one existed."""
    unit = _get_unit(project_id, org_unit_id)
    presets = db.session.get(MapOrgUnitVaPresets, unit.org_unit_id)
    if presets is None:
        return False
    db.session.delete(presets)
    db.session.flush()
    return True


def list_project_va_presets(project_id: str) -> list[dict]:
    """All active units of *project_id* with own and resolved (inherited) HIV/malaria presets."""
    from app.services.org_grant_service import resolve_unit_va_presets

    _get_project(project_id)
    units = list_units(project_id, include_inactive=False)
    if not units:
        return []
    unit_uuids = [uuid.UUID(u["org_unit_id"]) for u in units]
    own_rows = {
        str(row.org_unit_id): row
        for row in db.session.scalars(
            sa.select(MapOrgUnitVaPresets).where(MapOrgUnitVaPresets.org_unit_id.in_(unit_uuids))
        ).all()
    }
    resolved_map = resolve_unit_va_presets(unit_uuids)
    result = []
    for u in units:
        uid = u["org_unit_id"]
        u_uuid = uuid.UUID(uid)
        own = own_rows.get(uid)
        res = resolved_map.get(u_uuid, {})
        hiv_res = res.get("hiv_mortality")
        mal_res = res.get("malaria_mortality")
        own_hiv = own.hiv_mortality if own else None
        own_mal = own.malaria_mortality if own else None
        eff_hiv = hiv_res["value"] if hiv_res else None
        eff_mal = mal_res["value"] if mal_res else None
        hiv_src = (
            hiv_res["source_unit_name"]
            if hiv_res and str(hiv_res["source_unit_id"]) != uid
            else None
        )
        mal_src = (
            mal_res["source_unit_name"]
            if mal_res and str(mal_res["source_unit_id"]) != uid
            else None
        )
        result.append({
            "org_unit_id": uid,
            "org_level_id": u["org_level_id"],
            "unit_code": u["unit_code"],
            "unit_name": u["unit_name"],
            "level_code": u["level_code"],
            "level_name": u["level_name"],
            "depth": u["depth"],
            "parent_org_unit_id": u["parent_org_unit_id"],
            "path": u["path"],
            "own_hiv_mortality": own_hiv,
            "own_malaria_mortality": own_mal,
            "hiv_aids": own_hiv,
            "malaria": own_mal,
            "Id10002": own_hiv,
            "Id10003": own_mal,
            "effective_hiv_mortality": eff_hiv,
            "effective_hiv_aids": eff_hiv,
            "effective_Id10002": eff_hiv,
            "hiv_source_unit_name": hiv_src,
            "inherited_hiv_aids_from": hiv_src,
            "effective_malaria_mortality": eff_mal,
            "effective_malaria": eff_mal,
            "effective_Id10003": eff_mal,
            "malaria_source_unit_name": mal_src,
            "inherited_malaria_from": mal_src,
        })
    return result


def bulk_set_unit_va_presets(project_id: str, items: list[dict], *, actor_id=None) -> int:
    """Update HIV/malaria presets across multiple units of *project_id* in one batch without N+1 queries."""
    _get_project(project_id)
    if not isinstance(items, list):
        raise OrganizationError("items must be a list of unit preset updates.")
    if len(items) > 1000:
        raise OrganizationError("At most 1000 units can be updated in one request.")
    if not items:
        return 0

    project_units = {
        u.org_unit_id: u
        for u in db.session.scalars(
            sa.select(MasOrgUnit).where(MasOrgUnit.project_id == project_id)
        ).all()
    }
    existing_presets = {
        row.org_unit_id: row
        for row in db.session.scalars(
            sa.select(MapOrgUnitVaPresets).where(
                MapOrgUnitVaPresets.org_unit_id.in_(list(project_units.keys()))
            )
        ).all()
    }

    updated = 0
    for item in items:
        if not isinstance(item, dict):
            raise OrganizationError("Each preset entry must be an object.")
        uid = _uuid(item.get("org_unit_id"), what="Unit id")
        if uid not in project_units:
            raise OrganizationError("Unit does not belong to this project.")
        raw_hiv = (
            item.get("hiv_mortality")
            if "hiv_mortality" in item
            else (item.get("hiv_aids") if "hiv_aids" in item else item.get("Id10002"))
        )
        raw_mal = (
            item.get("malaria_mortality")
            if "malaria_mortality" in item
            else (item.get("malaria") if "malaria" in item else item.get("Id10003"))
        )
        hiv = _validate_va_preset_value(raw_hiv, what="hiv_mortality")
        malaria = _validate_va_preset_value(raw_mal, what="malaria_mortality")
        row = existing_presets.get(uid)
        if hiv is None and malaria is None:
            if row is not None:
                db.session.delete(row)
                del existing_presets[uid]
                updated += 1
        elif row is None:
            row = MapOrgUnitVaPresets(
                org_unit_id=uid,
                hiv_mortality=hiv,
                malaria_mortality=malaria,
                updated_by_user_id=actor_id,
            )
            db.session.add(row)
            existing_presets[uid] = row
            updated += 1
        elif row.hiv_mortality != hiv or row.malaria_mortality != malaria:
            row.hiv_mortality = hiv
            row.malaria_mortality = malaria
            row.updated_by_user_id = actor_id
            updated += 1

    db.session.flush()
    return updated


def project_mentoring_overview(project_id: str) -> dict:
    """Districts, attached mentoring institutes, institute scientists, and their unit grants in *project_id*."""
    from app.models import MapMentorInstituteOrgUnit, MapMentorInstituteUser, MasMentorInstitute
    from app.services.mentor_institute_service import MENTOR_ROLES

    _get_project(project_id)
    units = list_units(project_id, include_inactive=False)
    has_district_level = any(u.get("level_code") == "district" for u in units) or any(
        lv.level_code == "district" for lv in list_levels(project_id, include_inactive=False)
    )
    districts = [
        u for u in units
        if (u["level_code"] == "district" if has_district_level else u["depth"] == 1)
    ]
    district_uuids = [uuid.UUID(d["org_unit_id"]) for d in districts]

    inst_objs = db.session.scalars(
        sa.select(MasMentorInstitute)
        .where(MasMentorInstitute.is_active.is_(True))
        .order_by(MasMentorInstitute.institute_code)
    ).all()

    links = []
    attached_inst_ids: set[uuid.UUID] = set()
    districts_by_inst: dict[uuid.UUID, list[str]] = {}
    if district_uuids:
        link_rows = db.session.execute(
            sa.select(MapMentorInstituteOrgUnit, MasMentorInstitute, MasOrgUnit)
            .join(
                MasMentorInstitute,
                MasMentorInstitute.institute_id == MapMentorInstituteOrgUnit.institute_id,
            )
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == MapMentorInstituteOrgUnit.org_unit_id)
            .where(
                MapMentorInstituteOrgUnit.org_unit_id.in_(district_uuids),
                MapMentorInstituteOrgUnit.is_active.is_(True),
                MasMentorInstitute.is_active.is_(True),
            )
            .order_by(MasOrgUnit.unit_code, MasMentorInstitute.institute_code)
        ).all()
        for link, inst, dist in link_rows:
            attached_inst_ids.add(inst.institute_id)
            districts_by_inst.setdefault(inst.institute_id, []).append(str(dist.org_unit_id))
            links.append({
                "institute_id": str(inst.institute_id),
                "institute_code": inst.institute_code,
                "institute_name": inst.institute_name,
                "org_unit_id": str(dist.org_unit_id),
                "unit_code": dist.unit_code,
                "unit_name": dist.unit_name,
            })

    scientists = []
    scientists_by_inst: dict[uuid.UUID, list[dict]] = {}
    if attached_inst_ids:
        staff_rows = db.session.execute(
            sa.select(VaUsers, MapMentorInstituteUser, MasMentorInstitute)
            .join(MapMentorInstituteUser, MapMentorInstituteUser.user_id == VaUsers.user_id)
            .join(
                MasMentorInstitute,
                MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
            )
            .where(
                MapMentorInstituteUser.institute_id.in_(attached_inst_ids),
                MapMentorInstituteUser.is_active.is_(True),
                VaUsers.user_status == VaStatuses.active,
            )
            .order_by(MasMentorInstitute.institute_code, VaUsers.name, VaUsers.email)
        ).all()
        staff_user_ids = {u.user_id for u, _, _ in staff_rows}
        grants_by_user: dict[uuid.UUID, list[dict]] = {}
        if staff_user_ids:
            g_rows = db.session.execute(
                sa.select(VaUserAccessGrants, MasOrgUnit)
                .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
                .where(
                    VaUserAccessGrants.user_id.in_(staff_user_ids),
                    VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                    VaUserAccessGrants.grant_status == VaStatuses.active,
                    VaUserAccessGrants.role.in_(MENTOR_ROLES),
                    MasOrgUnit.project_id == project_id,
                    MasOrgUnit.is_active.is_(True),
                )
                .order_by(MasOrgUnit.path)
            ).all()
            for g, u in g_rows:
                grants_by_user.setdefault(g.user_id, []).append({
                    "grant_id": str(g.grant_id),
                    "role": g.role.value,
                    "org_unit_id": str(u.org_unit_id),
                    "unit_code": u.unit_code,
                    "unit_name": u.unit_name,
                })
        for u, member_link, inst in staff_rows:
            user_grants = grants_by_user.get(u.user_id, [])
            grants_by_role: dict[str, list[str]] = {}
            for g_item in user_grants:
                grants_by_role.setdefault(g_item["role"], []).append(g_item["org_unit_id"])
            sci_entry = {
                "user_id": str(u.user_id),
                "name": u.name,
                "email": u.email,
                "phone": u.phone or u.mobile_login,
                "mobile": u.phone or u.mobile_login,
                "coding_languages": list(u.vacode_language or []),
                "institute_code": inst.institute_code,
                "institute_name": inst.institute_name,
                "is_institute_admin": bool(member_link.is_admin),
                "grants": user_grants,
                "grants_by_role": grants_by_role,
            }
            scientists_by_inst.setdefault(inst.institute_id, []).append(sci_entry)
            scientists.append(sci_entry)

    all_institutes = [
        {
            "institute_id": str(inst.institute_id),
            "mentor_institute_id": str(inst.institute_id),
            "institute_code": inst.institute_code,
            "institute_name": inst.institute_name,
            "is_active": inst.is_active,
            "project_district_unit_ids": districts_by_inst.get(inst.institute_id, []),
        }
        for inst in inst_objs
    ]
    institutes = [
        {
            "institute_id": str(inst.institute_id),
            "mentor_institute_id": str(inst.institute_id),
            "institute_code": inst.institute_code,
            "institute_name": inst.institute_name,
            "is_active": inst.is_active,
            "project_district_unit_ids": districts_by_inst.get(inst.institute_id, []),
            "scientists": scientists_by_inst.get(inst.institute_id, []),
        }
        for inst in inst_objs
        if inst.institute_id in attached_inst_ids
    ]

    return {
        "units": units,
        "districts": districts,
        "all_institutes": all_institutes,
        "institutes": institutes,
        "attached_links": links,
        "scientists": scientists,
        "mentor_roles": ["coder", "reviewer", "coding_tester", "collaborator"],
    }


def sync_mentor_scientist_unit_grants(
    project_id: str,
    *,
    user_id: object,
    role_name: str,
    org_unit_ids: Iterable[object],
    actor: VaUsers,
) -> list[tuple[dict, str]]:
    """Sync a mentoring-institute scientist's unit grants for *role_name* in *project_id*."""
    from app.services.mentor_institute_service import MENTOR_ROLES
    from app.services.org_grant_service import validate_org_unit_grant

    _get_project(project_id)
    target_user_uuid = _uuid(user_id, what="Scientist user id")
    user = db.session.get(VaUsers, target_user_uuid)
    if user is None or user.user_status != VaStatuses.active:
        raise OrganizationError("Active scientist account not found.")
    try:
        role = VaAccessRoles(str(role_name or "").strip())
    except ValueError as exc:
        raise OrganizationError(f"Invalid role {role_name!r}.") from exc
    if role not in MENTOR_ROLES:
        raise OrganizationError(f"Role {role.value!r} is not a mentoring institute role.")

    target_ids: list[uuid.UUID] = []
    for raw in org_unit_ids or ():
        uid = _uuid(raw, what="Unit id")
        if uid not in target_ids:
            target_ids.append(uid)

    project_units = {
        u.org_unit_id: u
        for u in db.session.scalars(
            sa.select(MasOrgUnit).where(
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.is_active.is_(True),
            )
        ).all()
    }
    for uid in target_ids:
        if uid not in project_units:
            raise OrganizationError("Selected unit does not belong to this project or is inactive.")

    existing_grants = {
        g.org_unit_id: g
        for g in db.session.scalars(
            sa.select(VaUserAccessGrants)
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .where(
                VaUserAccessGrants.user_id == target_user_uuid,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                MasOrgUnit.project_id == project_id,
            )
        ).all()
    }
    actor_grants = authz.resolve_grants(actor)
    changed: list[tuple[dict, str]] = []

    for uid in target_ids:
        # A mentor grant carries no cadre (digitva-4650); validate_org_unit_grant
        # runs the institute guard.
        validate_org_unit_grant(role=role, org_unit_id=uid, user_id=target_user_uuid)
        if not authz.can_grant(
            actor,
            authz.GrantTarget(
                role=role,
                scope_type=VaAccessScopeTypes.org_unit,
                project_id=None,
                org_unit_id=uid,
            ),
            _grants=actor_grants,
        ):
            raise OrganizationError("You are not permitted to grant this role on the selected unit.")
        g = existing_grants.get(uid)
        if g is None:
            g = VaUserAccessGrants(
                user_id=target_user_uuid,
                role=role,
                scope_type=VaAccessScopeTypes.org_unit,
                project_id=None,
                org_unit_id=uid,
                grant_status=VaStatuses.active,
                created_by_user_id=actor.user_id,
            )
            db.session.add(g)
            db.session.flush()
            existing_grants[uid] = g
            changed.append((
                {
                    "user_id": target_user_uuid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": uid,
                    "cadre_id": None,
                },
                "grant_created",
            ))
        elif g.grant_status != VaStatuses.active:
            g.grant_status = VaStatuses.active
            g.cadre_id = None
            changed.append((
                {
                    "user_id": target_user_uuid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": uid,
                    "cadre_id": g.cadre_id,
                },
                "grant_reactivated",
            ))

    target_set = set(target_ids)
    for uid, g in list(existing_grants.items()):
        if uid not in target_set and g.grant_status == VaStatuses.active:
            g.grant_status = VaStatuses.deactive
            changed.append((
                {
                    "user_id": target_user_uuid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": uid,
                    "cadre_id": g.cadre_id,
                },
                "grant_revoked",
            ))

    db.session.flush()
    return changed
