"""Organization workers, existing-account lookup and per-worker unit scope grants."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa

from app import db
from app.models import (
    MasCadre,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import authz
from app.services.org_cadres import (
    _get_cadre,
    get_level_cadre_permission,
)
from app.services.org_common import (
    OrganizationError,
    _clean_text,
    _get_project,
    _uuid,
    normalize_code,
)
from app.services.org_levels_units import (
    _get_unit,
)


def serialize_worker(
    worker: MasOrgUnitWorker,
    *,
    unit: MasOrgUnit,
    cadre: MasCadre,
    user_email: str | None,
    coding_unit_ids: list[str] | None = None,
    coding_unit_codes: list[str] | None = None,
    supervision_unit_ids: list[str] | None = None,
    supervision_unit_codes: list[str] | None = None,
    active_roles: list[str] | None = None,
) -> dict:
    return {
        "worker_id": str(worker.worker_id),
        "project_id": worker.project_id,
        "org_unit_id": str(worker.org_unit_id),
        "unit_code": unit.unit_code,
        "unit_name": unit.unit_name,
        "cadre_id": str(worker.cadre_id),
        "cadre_code": cadre.cadre_code,
        "worker_code": worker.worker_code,
        "worker_name": worker.worker_name,
        "phone": worker.phone,
        "user_id": str(worker.user_id) if worker.user_id else None,
        "user_email": user_email,
        "remarks": worker.remarks,
        "is_active": worker.is_active,
        "coding_unit_ids": list(coding_unit_ids or []),
        "coding_unit_codes": list(coding_unit_codes or []),
        "supervision_unit_ids": list(supervision_unit_ids or []),
        "supervision_unit_codes": list(supervision_unit_codes or []),
        "active_roles": list(active_roles or []),
    }


_WORKER_CODING_ROLES = frozenset({
    VaAccessRoles.coder,
    VaAccessRoles.reviewer,
    VaAccessRoles.coding_tester,
})


_WORKER_SUPERVISION_ROLES = frozenset({
    VaAccessRoles.interview_supervisor,
})


def list_workers(project_id: str, *, include_inactive: bool = False, org_unit_id: object | None = None) -> list[dict]:
    stmt = (
        sa.select(MasOrgUnitWorker, MasOrgUnit, MasCadre, VaUsers.email)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
        .join(MasCadre, MasCadre.cadre_id == MasOrgUnitWorker.cadre_id)
        .outerjoin(VaUsers, VaUsers.user_id == MasOrgUnitWorker.user_id)
        .where(MasOrgUnitWorker.project_id == project_id)
    )
    if org_unit_id:
        stmt = stmt.where(MasOrgUnitWorker.org_unit_id == _uuid(org_unit_id, what="Unit id"))
    if not include_inactive:
        stmt = stmt.where(MasOrgUnitWorker.is_active.is_(True))
    rows = db.session.execute(stmt.order_by(MasOrgUnit.path, MasOrgUnitWorker.worker_code)).all()
    user_ids = {worker.user_id for worker, _, _, _ in rows if worker.user_id is not None}
    grants_by_user: dict[uuid.UUID, list[tuple[VaAccessRoles, uuid.UUID, str, uuid.UUID]]] = {}
    if user_ids:
        grant_rows = db.session.execute(
            sa.select(
                VaUserAccessGrants.user_id,
                VaUserAccessGrants.role,
                MasOrgUnit.org_unit_id,
                MasOrgUnit.unit_code,
                MasOrgUnit.org_level_id,
            )
            .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .where(
                VaUserAccessGrants.user_id.in_(user_ids),
                VaUserAccessGrants.grant_status == VaStatuses.active,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.is_active.is_(True),
            )
            .order_by(MasOrgUnit.path)
        ).all()
        for uid, role, u_id, u_code, u_level_id in grant_rows:
            grants_by_user.setdefault(uid, []).append((role, u_id, u_code, u_level_id))

    result = []
    for worker, unit, cadre, email in rows:
        coding_ids: list[str] = []
        coding_codes: list[str] = []
        sup_ids: list[str] = []
        sup_codes: list[str] = []
        roles_set: set[str] = set()
        if worker.user_id and worker.user_id in grants_by_user:
            for role, u_id, u_code, u_level_id in grants_by_user[worker.user_id]:
                roles_set.add(role.value if hasattr(role, "value") else str(role))
                u_id_str = str(u_id)
                if u_level_id == unit.org_level_id:
                    if role in _WORKER_CODING_ROLES and u_id_str not in coding_ids:
                        coding_ids.append(u_id_str)
                        coding_codes.append(u_code)
                    if role in _WORKER_SUPERVISION_ROLES and u_id_str not in sup_ids:
                        sup_ids.append(u_id_str)
                        sup_codes.append(u_code)
        result.append(
            serialize_worker(
                worker,
                unit=unit,
                cadre=cadre,
                user_email=email,
                coding_unit_ids=coding_ids,
                coding_unit_codes=coding_codes,
                supervision_unit_ids=sup_ids,
                supervision_unit_codes=sup_codes,
                active_roles=sorted(roles_set),
            )
        )
    return result


def _get_worker(project_id: str, worker_id: object) -> MasOrgUnitWorker:
    worker = db.session.get(MasOrgUnitWorker, _uuid(worker_id, what="Worker id"))
    if worker is None or worker.project_id != project_id:
        raise OrganizationError("Worker not found in this project.")
    return worker


def _require_cadre_at_unit_level(unit: MasOrgUnit, cadre: MasCadre) -> None:
    if not cadre.is_active:
        raise OrganizationError(f"Cadre {cadre.cadre_code!r} is inactive.")
    if get_level_cadre_permission(unit.org_level_id, cadre.cadre_id) is None:
        raise OrganizationError(
            f"Cadre {cadre.cadre_code!r} is not defined at level {unit.level.level_code!r}; "
            "add it in the level permissions grid first."
        )


def resolve_user(raw: object, *, require_active: bool = True) -> VaUsers | None:
    """Resolve a worker account, refusing inactive accounts by default.

    Existing worker links may point to an account that was deactivated later;
    callers updating that worker can pass ``require_active=False`` and decide
    whether the link is unchanged. New links must use the default guard.
    """
    if isinstance(raw, VaUsers):
        user = raw
    else:
        value = str(raw or "").strip()
        if not value:
            return None
        user = None
        try:
            user = db.session.get(VaUsers, uuid.UUID(value))
        except ValueError:
            user = db.session.scalar(sa.select(VaUsers).where(sa.func.lower(VaUsers.email) == value.lower()))
        if user is None:
            raise OrganizationError(f"DigitVA user not found: {value}")
    if require_active and user.user_status != VaStatuses.active:
        raise OrganizationError("DigitVA user is inactive.")
    return user


def _resolve_user(raw: object) -> VaUsers | None:
    """Backward-compatible private alias for existing import callers."""
    return resolve_user(raw)


def _next_worker_code(project_id: str) -> str:
    """Next free generated code, W00001, W00002, ... (one scan of this project's codes)."""
    codes = db.session.scalars(
        sa.select(MasOrgUnitWorker.worker_code).where(
            MasOrgUnitWorker.project_id == project_id, MasOrgUnitWorker.worker_code.like("W%")
        )
    ).all()
    numbers = [int(c[1:]) for c in codes if c[1:].isdigit()]
    return f"W{(max(numbers, default=0) + 1):05d}"


def create_worker(
    project_id: str,
    *,
    org_unit_id: object,
    cadre_id: object,
    worker_name: object,
    worker_code: object = None,
    phone: object = None,
    user: object = None,
    remarks: object = None,
) -> MasOrgUnitWorker:
    _get_project(project_id)
    unit = _get_unit(project_id, org_unit_id)
    cadre = _get_cadre(project_id, cadre_id)
    _require_cadre_at_unit_level(unit, cadre)
    # The code is an internal key (import matching); admins need not give one.
    if worker_code is None or not str(worker_code).strip():
        code = _next_worker_code(project_id)
    else:
        code = normalize_code(worker_code, what="Worker code")
    dup = db.session.scalar(
        sa.select(MasOrgUnitWorker.worker_id).where(
            MasOrgUnitWorker.project_id == project_id, MasOrgUnitWorker.worker_code == code
        )
    )
    if dup is not None:
        raise OrganizationError(f"Worker code {code!r} already exists in this project.")
    resolved_user = resolve_user(user)
    worker = MasOrgUnitWorker(
        project_id=project_id,
        org_unit_id=unit.org_unit_id,
        cadre_id=cadre.cadre_id,
        worker_code=code,
        worker_name=_clean_text(worker_name, required=True, what="Worker name"),
        phone=_clean_text(phone, max_len=32, what="Phone"),
        user_id=resolved_user.user_id if resolved_user else None,
        remarks=_clean_text(remarks, what="Remarks"),
    )
    db.session.add(worker)
    db.session.flush()
    return worker


def update_worker(project_id: str, worker_id: object, **fields) -> MasOrgUnitWorker:
    worker = _get_worker(project_id, worker_id)
    resolved_user = None
    if "user" in fields:
        # Resolve before mutating any other worker field so a refused relink
        # leaves the in-memory object unchanged for direct service callers.
        resolved_user = resolve_user(fields["user"], require_active=False)
        if (
            resolved_user is not None
            and resolved_user.user_status != VaStatuses.active
            and resolved_user.user_id != worker.user_id
        ):
            raise OrganizationError("DigitVA user is inactive.")
    unit = worker.unit
    cadre = worker.cadre
    if "org_unit_id" in fields and fields["org_unit_id"]:
        unit = _get_unit(project_id, fields["org_unit_id"])
    if "cadre_id" in fields and fields["cadre_id"]:
        cadre = _get_cadre(project_id, fields["cadre_id"])
    if unit.org_unit_id != worker.org_unit_id or cadre.cadre_id != worker.cadre_id:
        _require_cadre_at_unit_level(unit, cadre)
        worker.org_unit_id = unit.org_unit_id
        worker.cadre_id = cadre.cadre_id
    if "worker_code" in fields and fields["worker_code"] is not None:
        new_code = normalize_code(fields["worker_code"], what="Worker code")
        if new_code != worker.worker_code:
            dup = db.session.scalar(
                sa.select(MasOrgUnitWorker.worker_id).where(
                    MasOrgUnitWorker.project_id == project_id, MasOrgUnitWorker.worker_code == new_code
                )
            )
            if dup is not None:
                raise OrganizationError(f"Worker code {new_code!r} already exists in this project.")
            worker.worker_code = new_code
    if "worker_name" in fields:
        worker.worker_name = _clean_text(fields["worker_name"], required=True, what="Worker name")
    if "phone" in fields:
        worker.phone = _clean_text(fields["phone"], max_len=32, what="Phone")
    if "user" in fields:
        # Editing an existing worker must not unexpectedly unlink it just
        # because the linked account was deactivated after the original link.
        worker.user_id = resolved_user.user_id if resolved_user else None
    if "remarks" in fields:
        worker.remarks = _clean_text(fields["remarks"], what="Remarks")
    if "is_active" in fields:
        worker.is_active = bool(fields["is_active"])
    db.session.flush()
    return worker


def lookup_existing_user(query: object, *, is_admin: bool = True) -> dict:
    """Exact email or 10-digit mobile match on active VaUsers for Add/Edit Worker UI."""
    from app.services.mentor_institute_service import member_user_ids
    from app.services.user_account_service import PHONE_CANONICAL, canonical_mobile

    raw = str(query or "").strip()
    if not raw:
        return {"found": False}
    user = None
    matched_by_email = "@" in raw
    if matched_by_email:
        user = db.session.scalar(
            sa.select(VaUsers).where(
                sa.func.lower(VaUsers.email) == raw.lower(),
                VaUsers.user_status == VaStatuses.active,
            )
        )
    else:
        mobile = canonical_mobile(raw)
        if mobile:
            user = db.session.scalar(
                sa.select(VaUsers).where(
                    sa.or_(VaUsers.mobile_login == mobile, PHONE_CANONICAL == mobile),
                    VaUsers.user_status == VaStatuses.active,
                )
            )
    if user is None:
        return {"found": False}
    is_mentor = user.user_id in member_user_ids([user.user_id])
    # Do not disclose the unqueried contact channel to non-admin callers.
    email_out = user.email if (is_admin or matched_by_email) else None
    phone_out = (user.phone or user.mobile_login) if (is_admin or not matched_by_email) else None
    status_str = user.user_status.value if hasattr(user.user_status, "value") else str(user.user_status)
    user_payload = {
        "user_id": str(user.user_id),
        "name": user.name,
        "email": email_out,
        "phone": phone_out,
        "mobile": phone_out,
        "is_active": user.user_status == VaStatuses.active,
        "user_status": status_str,
        "coding_languages": list(user.vacode_language or []),
        "is_mentor_member": is_mentor,
    }
    return {
        "found": True,
        **user_payload,
        "user": user_payload,
    }


SUGGEST_LIMIT = 8


SUGGEST_MIN_EMAIL = 3


SUGGEST_MIN_DIGITS = 4


SUGGEST_MAX_LEN = 128


def suggest_existing_users(query: object, *, is_admin: bool = True) -> list[dict]:
    """Up to 8 active accounts whose email (any text with a letter or ``@``,
    from 3 characters) or canonical mobile (digits only, from 4) contains
    *query*, case-insensitive: exact match first, then prefix, then by name.
    An admin's text query also matches the account name (the admin training
    panel searches people by name).

    Owner decision 2026-10-22 (organization-model.md): any admin or project
    PI sees every matching account. A non-admin gets only the channel being
    typed, as in ``lookup_existing_user``. A short or overlong query returns [].
    """
    from app.services.user_account_service import PHONE_CANONICAL

    raw = str(query or "").strip().lower()
    if len(raw) > SUGGEST_MAX_LEN:
        return []
    by_email = not raw.isdigit()
    if by_email:
        if len(raw) < SUGGEST_MIN_EMAIL:
            return []
        field = sa.func.lower(VaUsers.email)
        match = field.contains(raw, autoescape=True)
        if is_admin:
            match = sa.or_(match, sa.func.lower(VaUsers.name).contains(raw, autoescape=True))
    else:
        if len(raw) < SUGGEST_MIN_DIGITS:
            return []
        field = sa.func.coalesce(VaUsers.mobile_login, PHONE_CANONICAL)
        match = field.contains(raw, autoescape=True)
    # ponytail: contains-match is a sequential scan; fine at ~1k accounts,
    # add a pg_trgm index on lower(email) and mobile_login past ~100k.
    rank = sa.case((field == raw, 0), (field.startswith(raw, autoescape=True), 1), else_=2)
    rows = db.session.execute(
        sa.select(VaUsers.user_id, VaUsers.name, VaUsers.email, VaUsers.phone, VaUsers.mobile_login)
        .where(match, VaUsers.user_status == VaStatuses.active)
        .order_by(rank, VaUsers.name, VaUsers.user_id)
        .limit(SUGGEST_LIMIT)
    ).all()
    suggestions = []
    for user_id, name, email, phone, mobile_login in rows:
        mobile = (phone or mobile_login) if (is_admin or not by_email) else None
        suggestions.append({
            "user_id": str(user_id),
            "name": name,
            "email": email if (is_admin or by_email) else None,
            "mobile": mobile,
        })
    return suggestions


def worker_data_collector_user(project_id: str, worker_id: object) -> VaUsers:
    """The active, emailable account behind a worker that holds an active
    interviewer or death_reporter grant in *project_id*, for the enrolment
    email resend. Raises OrganizationError naming what is missing."""
    worker = _get_worker(project_id, worker_id)
    user = db.session.get(VaUsers, worker.user_id) if worker.user_id else None
    if user is None or user.user_status != VaStatuses.active:
        raise OrganizationError("This worker has no active DigitVA account.")
    if not user.email:
        raise OrganizationError("This worker has no email; use the QR on the Devices page.")
    collector = db.session.scalar(
        sa.select(VaUserAccessGrants.grant_id)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.role.in_((VaAccessRoles.interviewer, VaAccessRoles.death_reporter)),
            sa.or_(VaUserAccessGrants.project_id == project_id, MasOrgUnit.project_id == project_id),
        )
        .limit(1)
    )
    if collector is None:
        raise OrganizationError("This worker is not an interviewer or death reporter in this project.")
    return user


def sync_worker_unit_scope_grants(
    project_id: str,
    worker: MasOrgUnitWorker,
    *,
    coding_unit_ids: Iterable[object] | None = None,
    supervision_unit_ids: Iterable[object] | None = None,
    actor: VaUsers,
) -> list[tuple[dict, str]]:
    """Sync a worker's multi-unit coding and/or supervision grants at their level.

    Allows configuring within-tree (own unit), cross-tree (other units at the
    same level), all units at the level, or a custom selection of units at the
    worker's level (e.g. 2 PHCs for one MO and 10 PHCs for another).
    Omitting ``coding_unit_ids`` or ``supervision_unit_ids`` leaves that bucket
    unchanged.
    """
    from app.services.org_grant_service import validate_org_unit_grant

    if coding_unit_ids is None and supervision_unit_ids is None:
        return []
    if worker.user_id is None:
        if (coding_unit_ids and list(coding_unit_ids)) or (supervision_unit_ids and list(supervision_unit_ids)):
            raise OrganizationError(
                "Link this worker to a DigitVA account (email or mobile) before assigning coding or supervision units."
            )
        return []

    unit = _get_unit(project_id, worker.org_unit_id)
    cadre = _get_cadre(project_id, worker.cadre_id)
    permission = get_level_cadre_permission(unit.org_level_id, cadre.cadre_id)
    if permission is None:
        raise OrganizationError(
            f"Cadre {cadre.cadre_code!r} is not active at level {unit.level.level_code!r}."
        )

    level_units = {
        u.org_unit_id: u
        for u in db.session.scalars(
            sa.select(MasOrgUnit).where(
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.org_level_id == unit.org_level_id,
                MasOrgUnit.is_active.is_(True),
            )
        ).all()
    }
    existing_grants = {
        (g.role, g.org_unit_id): g
        for g in db.session.scalars(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == worker.user_id,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                VaUserAccessGrants.org_unit_id.in_(list(level_units.keys())),
            )
        ).all()
    }
    actor_grants = authz.resolve_grants(actor)
    changed: list[tuple[dict, str]] = []

    def _sync_bucket(
        raw_ids: Iterable[object] | None,
        bucket_roles: frozenset[VaAccessRoles],
        fallback_role: VaAccessRoles,
    ) -> None:
        if raw_ids is None:
            return
        target_ids: list[uuid.UUID] = []
        for raw in raw_ids:
            uid = _uuid(raw, what="Unit id")
            if uid not in level_units:
                raise OrganizationError(
                    "Selected coding or supervision units must be active units at the worker's level in this project."
                )
            if uid not in target_ids:
                target_ids.append(uid)

        active_bucket_roles = {
            r for (r, _), g in existing_grants.items()
            if r in bucket_roles and g.grant_status == VaStatuses.active
        }
        default_bucket_roles = {
            VaAccessRoles(r) for r in (permission.default_roles or ())
            if r in {br.value for br in bucket_roles}
        }
        roles_to_sync = sorted(
            active_bucket_roles or default_bucket_roles or ({fallback_role} if target_ids else set()),
            key=lambda r: r.value,
        )

        for role in roles_to_sync:
            for uid in target_ids:
                validate_org_unit_grant(
                    role=role,
                    org_unit_id=uid,
                    cadre_id=cadre.cadre_id,
                    user_id=worker.user_id,
                )
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
                g = existing_grants.get((role, uid))
                if g is None:
                    g = VaUserAccessGrants(
                        user_id=worker.user_id,
                        role=role,
                        scope_type=VaAccessScopeTypes.org_unit,
                        project_id=None,
                        org_unit_id=uid,
                        cadre_id=cadre.cadre_id,
                        grant_status=VaStatuses.active,
                        created_by_user_id=actor.user_id,
                    )
                    db.session.add(g)
                    db.session.flush()
                    existing_grants[(role, uid)] = g
                    changed.append((
                        {
                            "user_id": worker.user_id,
                            "grant_id": g.grant_id,
                            "role": role.value,
                            "scope_type": VaAccessScopeTypes.org_unit.value,
                            "org_unit_id": uid,
                            "cadre_id": cadre.cadre_id,
                        },
                        "grant_created",
                    ))
                elif g.grant_status != VaStatuses.active or g.cadre_id != cadre.cadre_id:
                    was_active = g.grant_status == VaStatuses.active
                    g.grant_status = VaStatuses.active
                    g.cadre_id = cadre.cadre_id
                    changed.append((
                        {
                            "user_id": worker.user_id,
                            "grant_id": g.grant_id,
                            "role": role.value,
                            "scope_type": VaAccessScopeTypes.org_unit.value,
                            "org_unit_id": uid,
                            "cadre_id": cadre.cadre_id,
                        },
                        "grant_updated" if was_active else "grant_reactivated",
                    ))

        target_set = set(target_ids)
        for (role, uid), g in list(existing_grants.items()):
            if role in bucket_roles and uid not in target_set and g.grant_status == VaStatuses.active:
                g.grant_status = VaStatuses.deactive
                changed.append((
                    {
                        "user_id": worker.user_id,
                        "grant_id": g.grant_id,
                        "role": role.value,
                        "scope_type": VaAccessScopeTypes.org_unit.value,
                        "org_unit_id": uid,
                        "cadre_id": g.cadre_id,
                    },
                    "grant_revoked",
                ))

    _sync_bucket(coding_unit_ids, _WORKER_CODING_ROLES, VaAccessRoles.coder)
    _sync_bucket(supervision_unit_ids, _WORKER_SUPERVISION_ROLES, VaAccessRoles.interview_supervisor)
    db.session.flush()
    return changed
