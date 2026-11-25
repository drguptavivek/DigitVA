"""ApplyContext: the state one bulk grid apply and its operations share (digitva-r8nh.14)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgLevelCadre,
    MasCadre,
    MasOrgLevel,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import authz
from app.services.org_common import (
    OrganizationError,
    _uuid,
)


@dataclass
class ApplyContext:
    """State shared by one ``bulk_apply_project_users_grid`` call and its operations.

    ``load`` preloads the project's units, cadre permissions, workers and existing
    grants in bulk; ``validate_scope`` checks the custom-unit and level inputs of
    ``scope_mode``. ``summary`` and ``changed_grants`` are what the call returns.
    The grant helpers keep the grant maps current, so a later helper in the same
    call sees the writes of an earlier one.
    """

    project: object
    project_id: str
    actor: VaUsers
    operation: str
    scope_mode: str
    sync_scope: bool
    payload: dict
    target_user_uuids: list[uuid.UUID]
    users_map: dict[uuid.UUID, VaUsers]
    summary: dict
    changed_grants: list[tuple[dict, str]] = field(default_factory=list)

    def load(self) -> None:
        # Preload project units, level_cadres, workers, and existing grants in bulk
        self.active_units = {
            u.org_unit_id: u
            for u in db.session.scalars(
                sa.select(MasOrgUnit).where(
                    MasOrgUnit.project_id == self.project_id,
                    MasOrgUnit.is_active.is_(True),
                )
            ).all()
        }
        self.all_project_unit_ids = list(
            db.session.scalars(
                sa.select(MasOrgUnit.org_unit_id).where(MasOrgUnit.project_id == self.project_id)
            ).all()
        )
        self.units_by_level_id: dict[uuid.UUID, list[MasOrgUnit]] = {}
        for u in self.active_units.values():
            self.units_by_level_id.setdefault(u.org_level_id, []).append(u)

        self.project_sites = list(
            db.session.scalars(
                sa.select(VaProjectSites).where(VaProjectSites.project_id == self.project_id)
            ).all()
        )
        ps_ids = [ps.project_site_id for ps in self.project_sites]

        # Preload active MapOrgLevelCadre for automatic cadre resolution
        lc_rows = db.session.execute(
            sa.select(MapOrgLevelCadre, MasCadre)
            .join(MasCadre, MasCadre.cadre_id == MapOrgLevelCadre.cadre_id)
            .join(MasOrgLevel, MasOrgLevel.org_level_id == MapOrgLevelCadre.org_level_id)
            .where(
                MasOrgLevel.project_id == self.project_id,
                MapOrgLevelCadre.is_active.is_(True),
                MasCadre.is_active.is_(True),
            )
            .order_by(MasCadre.cadre_code)
        ).all()
        self.lc_by_pair: dict[tuple[uuid.UUID, uuid.UUID], MapOrgLevelCadre] = {}
        self.lc_by_level: dict[uuid.UUID, list[tuple[MapOrgLevelCadre, MasCadre]]] = {}
        for lc, cadre in lc_rows:
            self.lc_by_pair[(lc.org_level_id, lc.cadre_id)] = lc
            self.lc_by_level.setdefault(lc.org_level_id, []).append((lc, cadre))

        # Preload workers for target users
        self.worker_rows = db.session.scalars(
            sa.select(MasOrgUnitWorker)
            .where(
                MasOrgUnitWorker.project_id == self.project_id,
                MasOrgUnitWorker.user_id.in_(self.target_user_uuids),
            )
            .order_by(MasOrgUnitWorker.is_active.desc(), MasOrgUnitWorker.worker_code)
        ).all()
        self.primary_worker_by_user: dict[uuid.UUID, MasOrgUnitWorker] = {}
        for w in self.worker_rows:
            if w.user_id and w.user_id not in self.primary_worker_by_user:
                self.primary_worker_by_user[w.user_id] = w

        # Preload all existing grants in this project for target users
        grant_conds = [
            sa.and_(
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
                VaUserAccessGrants.project_id == self.project_id,
            )
        ]
        if ps_ids:
            grant_conds.append(
                sa.and_(
                    VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                    VaUserAccessGrants.project_site_id.in_(ps_ids),
                )
            )
        if self.all_project_unit_ids:
            grant_conds.append(
                sa.and_(
                    VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                    VaUserAccessGrants.org_unit_id.in_(self.all_project_unit_ids),
                )
            )
        existing_grant_rows = db.session.scalars(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id.in_(self.target_user_uuids),
                sa.or_(*grant_conds),
            )
        ).all()

        self.proj_grants_map: dict[tuple[uuid.UUID, VaAccessRoles], VaUserAccessGrants] = {}
        self.site_grants_map: dict[tuple[uuid.UUID, VaAccessRoles, uuid.UUID], VaUserAccessGrants] = {}
        self.unit_grants_map: dict[tuple[uuid.UUID, VaAccessRoles, uuid.UUID], VaUserAccessGrants] = {}
        self.all_user_project_grants: dict[uuid.UUID, list[VaUserAccessGrants]] = {}

        for g in existing_grant_rows:
            self.all_user_project_grants.setdefault(g.user_id, []).append(g)
            if g.scope_type == VaAccessScopeTypes.project:
                self.proj_grants_map[(g.user_id, g.role)] = g
            elif g.scope_type == VaAccessScopeTypes.project_site and g.project_site_id:
                self.site_grants_map[(g.user_id, g.role, g.project_site_id)] = g
            elif g.scope_type == VaAccessScopeTypes.org_unit and g.org_unit_id:
                self.unit_grants_map[(g.user_id, g.role, g.org_unit_id)] = g

        from app.services.mentor_institute_service import member_user_ids

        self.mentor_user_ids = member_user_ids(self.target_user_uuids)
        self.actor_grants = authz.resolve_grants(self.actor)

    def validate_scope(self) -> None:
        self.custom_unit_uuids: list[uuid.UUID] = []
        if self.scope_mode == "custom":
            raw_custom = self.payload.get("custom_unit_ids") or []
            if not isinstance(raw_custom, list) or not raw_custom:
                raise OrganizationError("Pick at least one target unit when using custom unit selection.")
            for raw_cu in raw_custom:
                cu_uuid = _uuid(raw_cu, what="Unit id")
                if cu_uuid not in self.active_units:
                    raise OrganizationError("Selected unit does not belong to this project or is inactive.")
                if cu_uuid not in self.custom_unit_uuids:
                    self.custom_unit_uuids.append(cu_uuid)

        self.level_scope_uuid: uuid.UUID | None = None
        if self.scope_mode.startswith("level:"):
            self.level_scope_uuid = _uuid(self.scope_mode.split(":", 1)[1], what="Level id")
            if not self.units_by_level_id.get(self.level_scope_uuid):
                raise OrganizationError("There are no active units at the selected hierarchy level.")

    def revoke_grant(self, g: VaUserAccessGrants) -> None:
        if g.grant_status != VaStatuses.active:
            return
        if not authz.can_grant(
            self.actor,
            authz.GrantTarget(
                role=g.role,
                scope_type=g.scope_type,
                project_id=g.project_id,
                project_site_id=g.project_site_id,
                org_unit_id=g.org_unit_id,
            ),
            _grants=self.actor_grants,
        ):
            raise OrganizationError(f"You are not permitted to revoke {g.role.value!r}.")
        g.grant_status = VaStatuses.deactive
        self.summary["grants_revoked"] += 1
        self.changed_grants.append((
            {
                "user_id": g.user_id,
                "grant_id": g.grant_id,
                "role": g.role.value,
                "scope_type": g.scope_type.value,
                "project_id": g.project_id,
                "project_site_id": g.project_site_id,
                "org_unit_id": g.org_unit_id,
                "cadre_id": g.cadre_id,
            },
            "grant_revoked",
        ))

    def resolve_user_target_units(self, uid: uuid.UUID) -> list[uuid.UUID]:
        if self.scope_mode == "custom":
            return list(self.custom_unit_uuids)
        if self.level_scope_uuid is not None:
            return [u.org_unit_id for u in self.units_by_level_id.get(self.level_scope_uuid, [])]
        worker = self.primary_worker_by_user.get(uid)
        if worker is None or worker.org_unit_id not in self.active_units:
            if len(self.target_user_uuids) == 1:
                raise OrganizationError(
                    f"{self.users_map[uid].name or self.users_map[uid].email} has no home unit placement in this project yet. "
                    "Choose 'All units at Level…', 'Pick specific unit(s)…', or 'Project-wide' in Dropdown 2."
                )
            return []
        home_unit = self.active_units[worker.org_unit_id]
        if self.scope_mode == "own":
            return [home_unit.org_unit_id]
        lv_units = [u.org_unit_id for u in self.units_by_level_id.get(home_unit.org_level_id, [])]
        if self.scope_mode == "cross_level":
            other_units = [u_id for u_id in lv_units if u_id != home_unit.org_unit_id]
            if not other_units and len(self.target_user_uuids) == 1:
                raise OrganizationError(
                    f"There are no other active units at {home_unit.level.level_name!r} besides {home_unit.unit_code!r}."
                )
            return other_units
        if self.scope_mode == "all_user_level":
            return lv_units
        raise OrganizationError(f"Unsupported scope_mode {self.scope_mode!r}.")

    def resolve_cadre_for_unit_grant(self,
        uid: uuid.UUID,
        role: VaAccessRoles,
        unit: MasOrgUnit,
    ) -> uuid.UUID | None:
        """The cadre a unit grant of *role* at *unit* carries (digitva-4650).

        A mentoring-institute member's grant carries their worker cadre only
        at the unit their worker record places them (a health-system grant);
        anywhere else none (a mentor grant). Anyone else's names their home
        worker cadre, which must allow *role* at the unit's level; with no
        worker, the first active cadre at the level that allows it.
        ``validate_org_unit_grant`` still checks the result.
        """
        worker = self.primary_worker_by_user.get(uid)
        if uid in self.mentor_user_ids:
            if worker and worker.is_active and worker.org_unit_id == unit.org_unit_id:
                return worker.cadre_id
            return None
        home_cadre_id = worker.cadre_id if worker else None
        if home_cadre_id is not None:
            cadre_code = worker.cadre.cadre_code if worker.cadre else str(home_cadre_id)
            lc = self.lc_by_pair.get((unit.org_level_id, home_cadre_id))
            if lc is None:
                raise OrganizationError(
                    f"Cadre {cadre_code!r} is not defined at level "
                    f"{unit.level.level_code!r}; add it in the level permissions grid first."
                )
            if role.value not in (lc.allowed_roles or ()):
                raise OrganizationError(
                    f"Cadre {cadre_code!r} may not hold {role.value} at level "
                    f"{unit.level.level_code!r}."
                )
            return home_cadre_id
        for lc, cadre in self.lc_by_level.get(unit.org_level_id, []):
            if role.value in (lc.allowed_roles or ()):
                return cadre.cadre_id
        raise OrganizationError(
            f"To grant {role.value!r} at {unit.unit_code!r} ({unit.level.level_name}), "
            "allow it for at least one cadre at that level in the Cadres & Role Matrix first."
        )

    def ensure_unit_grant(self, uid: uuid.UUID, role: VaAccessRoles, unit_id: uuid.UUID) -> None:
        from app.services.org_grant_service import validate_org_unit_grant

        if self.users_map[uid].user_status != VaStatuses.active:
            raise OrganizationError("DigitVA user is inactive.")
        unit = self.active_units[unit_id]
        cadre_id = self.resolve_cadre_for_unit_grant(uid, role, unit)
        validate_org_unit_grant(
            role=role,
            org_unit_id=unit_id,
            cadre_id=cadre_id,
            user_id=uid,
        )
        if not authz.can_grant(
            self.actor,
            authz.GrantTarget(
                role=role,
                scope_type=VaAccessScopeTypes.org_unit,
                project_id=None,
                org_unit_id=unit_id,
            ),
            _grants=self.actor_grants,
        ):
            raise OrganizationError(f"You are not permitted to grant {role.value!r} on {unit.unit_code!r}.")

        g = self.unit_grants_map.get((uid, role, unit_id))
        if g is None:
            g = VaUserAccessGrants(
                user_id=uid,
                role=role,
                scope_type=VaAccessScopeTypes.org_unit,
                project_id=None,
                org_unit_id=unit_id,
                cadre_id=cadre_id,
                grant_status=VaStatuses.active,
                created_by_user_id=self.actor.user_id,
            )
            db.session.add(g)
            db.session.flush()
            self.unit_grants_map[(uid, role, unit_id)] = g
            self.all_user_project_grants.setdefault(uid, []).append(g)
            self.summary["grants_created"] += 1
            self.changed_grants.append((
                {
                    "user_id": uid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": unit_id,
                    "cadre_id": cadre_id,
                },
                "grant_created",
            ))
        elif g.grant_status != VaStatuses.active or g.cadre_id != cadre_id:
            # The grant carries what was validated: a mentor grant drops a
            # borrowed cadre (digitva-4650).
            was_active = g.grant_status == VaStatuses.active
            g.grant_status = VaStatuses.active
            g.cadre_id = cadre_id
            if not was_active:
                self.summary["grants_reactivated"] += 1
            self.changed_grants.append((
                {
                    "user_id": uid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.org_unit.value,
                    "org_unit_id": unit_id,
                    "cadre_id": g.cadre_id,
                },
                "grant_updated" if was_active else "grant_reactivated",
            ))

    def ensure_project_grant(self, uid: uuid.UUID, role: VaAccessRoles) -> None:
        from app.services.mentor_institute_service import check_mentor_grant

        if self.users_map[uid].user_status != VaStatuses.active:
            raise OrganizationError("DigitVA user is inactive.")
        check_mentor_grant(uid, role, None)
        if role == VaAccessRoles.project_pi and not self.actor.is_admin():
            raise OrganizationError("Only a platform Admin can grant Project PI.")
        if role == VaAccessRoles.site_pi:
            # site_pi cannot use 'project' scope; grant across all active project_sites of this project
            active_project_sites = [
                ps for ps in self.project_sites if ps.project_site_status == VaStatuses.active
            ]
            if not active_project_sites:
                raise OrganizationError("This project has no sites configured yet.")
            for ps in active_project_sites:
                if not authz.can_grant(
                    self.actor,
                    authz.GrantTarget(
                        role=role,
                        scope_type=VaAccessScopeTypes.project_site,
                        project_site_id=ps.project_site_id,
                    ),
                    _grants=self.actor_grants,
                ):
                    raise OrganizationError("You are not permitted to grant Site PI on this site.")
                g = self.site_grants_map.get((uid, role, ps.project_site_id))
                if g is None:
                    g = VaUserAccessGrants(
                        user_id=uid,
                        role=role,
                        scope_type=VaAccessScopeTypes.project_site,
                        project_site_id=ps.project_site_id,
                        grant_status=VaStatuses.active,
                        created_by_user_id=self.actor.user_id,
                    )
                    db.session.add(g)
                    db.session.flush()
                    self.site_grants_map[(uid, role, ps.project_site_id)] = g
                    self.all_user_project_grants.setdefault(uid, []).append(g)
                    self.summary["grants_created"] += 1
                    self.changed_grants.append((
                        {
                            "user_id": uid,
                            "grant_id": g.grant_id,
                            "role": role.value,
                            "scope_type": VaAccessScopeTypes.project_site.value,
                            "project_site_id": ps.project_site_id,
                        },
                        "grant_created",
                    ))
                elif g.grant_status != VaStatuses.active:
                    g.grant_status = VaStatuses.active
                    self.summary["grants_reactivated"] += 1
                    self.changed_grants.append((
                        {
                            "user_id": uid,
                            "grant_id": g.grant_id,
                            "role": role.value,
                            "scope_type": VaAccessScopeTypes.project_site.value,
                            "project_site_id": ps.project_site_id,
                        },
                        "grant_reactivated",
                    ))
            return

        if role in (VaAccessRoles.interview_supervisor, VaAccessRoles.death_reporter):
            raise OrganizationError(f"Role {role.value!r} is unit-scoped and cannot be granted project-wide.")

        if not authz.can_grant(
            self.actor,
            authz.GrantTarget(
                role=role,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.project_id,
            ),
            _grants=self.actor_grants,
        ):
            raise OrganizationError(f"You are not permitted to grant {role.value!r} at project scope.")

        g = self.proj_grants_map.get((uid, role))
        if g is None:
            g = VaUserAccessGrants(
                user_id=uid,
                role=role,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.project_id,
                grant_status=VaStatuses.active,
                created_by_user_id=self.actor.user_id,
            )
            db.session.add(g)
            db.session.flush()
            self.proj_grants_map[(uid, role)] = g
            self.all_user_project_grants.setdefault(uid, []).append(g)
            self.summary["grants_created"] += 1
            self.changed_grants.append((
                {
                    "user_id": uid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.project.value,
                    "project_id": self.project_id,
                },
                "grant_created",
            ))
        elif g.grant_status != VaStatuses.active:
            g.grant_status = VaStatuses.active
            self.summary["grants_reactivated"] += 1
            self.changed_grants.append((
                {
                    "user_id": uid,
                    "grant_id": g.grant_id,
                    "role": role.value,
                    "scope_type": VaAccessScopeTypes.project.value,
                    "project_id": self.project_id,
                },
                "grant_reactivated",
            ))
