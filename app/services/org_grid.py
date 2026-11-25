"""Project users grid and the 2-dropdown bulk apply (digitva-dus.4)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectMember,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import authz
from app.services.org_cadres import (
    get_level_cadre_permission,
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
from app.services.org_grid_read import (  # noqa: F401  re-exported for organization_service
    _DISPLAY_ROLE_META,
    get_project_users_grid,
)
from app.services.org_levels_units import (
    _get_unit,
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
