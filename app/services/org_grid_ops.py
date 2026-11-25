"""Bulk grid operations: handlers, stages and the OPERATIONS registry (digitva-r8nh.14)."""

from __future__ import annotations

from collections.abc import Callable
from enum import IntEnum
from typing import NamedTuple

from app.models import (
    VaAccessRoles,
    VaStatuses,
)
from app.services.org_common import (
    OrganizationError,
)
from app.services.org_grid_context import ApplyContext

_BULK_ROLE_MAP: dict[str, tuple[list[VaAccessRoles], list[VaAccessRoles]]] = {
    # operation -> (roles_to_grant, roles_to_revoke_at_target)
    "coder": ([VaAccessRoles.coder], [VaAccessRoles.collaborator_pii]),
    "coder_non_pii": ([VaAccessRoles.coder], [VaAccessRoles.collaborator_pii]),
    "coder_pii": ([VaAccessRoles.coder], [VaAccessRoles.collaborator_pii]),
    "reviewer": ([VaAccessRoles.reviewer], [VaAccessRoles.collaborator_pii]),
    "reviewer_non_pii": ([VaAccessRoles.reviewer], [VaAccessRoles.collaborator_pii]),
    "reviewer_pii": ([VaAccessRoles.reviewer], [VaAccessRoles.collaborator_pii]),
    "coding_tester": ([VaAccessRoles.coding_tester], []),
    "viewer_non_pii": ([VaAccessRoles.collaborator], [VaAccessRoles.collaborator_pii]),
    "collaborator": ([VaAccessRoles.collaborator], [VaAccessRoles.collaborator_pii]),
    "viewer_pii": ([VaAccessRoles.collaborator_pii], []),
    "collaborator_pii": ([VaAccessRoles.collaborator_pii], []),
    "in_charge": ([VaAccessRoles.site_pi], []),
    "site_pi": ([VaAccessRoles.site_pi], []),
    "data_manager": ([VaAccessRoles.data_manager], []),
    "project_pi": ([VaAccessRoles.project_pi], []),
    "interviewer": ([VaAccessRoles.interviewer], []),
    "interview_supervisor": ([VaAccessRoles.interview_supervisor], []),
    "death_reporter": ([VaAccessRoles.death_reporter], []),
}


def _set_account_status(ctx: ApplyContext) -> None:
    """Admin-only: activate or deactivate the selected accounts."""
    if not ctx.actor.is_admin():
        raise OrganizationError("Only a platform Admin can activate or deactivate user accounts.")
    desired_status = VaStatuses.active if ctx.operation == "activate_users" else VaStatuses.deactive
    for uid in ctx.target_user_uuids:
        if desired_status == VaStatuses.deactive and uid == ctx.actor.user_id:
            raise OrganizationError("You cannot deactivate your own account.")
        u_obj = ctx.users_map[uid]
        if u_obj.user_status != desired_status:
            u_obj.user_status = desired_status
            ctx.summary["accounts_updated"] += 1


def _revoke_all(ctx: ApplyContext) -> None:
    """Revoke every grant the selected users hold in the project."""
    for uid in ctx.target_user_uuids:
        for g in ctx.all_user_project_grants.get(uid, []):
            ctx.revoke_grant(g)


def _revoke_pii(ctx: ApplyContext) -> None:
    """Downgrade to non-PII: revoke collaborator_pii at project or target-unit scope."""
    for uid in ctx.target_user_uuids:
        if ctx.scope_mode == "project":
            g = ctx.proj_grants_map.get((uid, VaAccessRoles.collaborator_pii))
            if g:
                ctx.revoke_grant(g)
            for u_id in ctx.all_project_unit_ids:
                ug = ctx.unit_grants_map.get((uid, VaAccessRoles.collaborator_pii, u_id))
                if ug:
                    ctx.revoke_grant(ug)
        else:
            target_units = ctx.resolve_user_target_units(uid)
            for u_id in target_units:
                ug = ctx.unit_grants_map.get((uid, VaAccessRoles.collaborator_pii, u_id))
                if ug:
                    ctx.revoke_grant(ug)


def _revoke_coder(ctx: ApplyContext) -> None:
    """Revoke the coding roles (coder, reviewer, coding_tester) at the target scope."""
    coding_roles = (VaAccessRoles.coder, VaAccessRoles.reviewer, VaAccessRoles.coding_tester)
    for uid in ctx.target_user_uuids:
        if ctx.scope_mode == "project":
            for r in coding_roles:
                g = ctx.proj_grants_map.get((uid, r))
                if g:
                    ctx.revoke_grant(g)
                for u_id in ctx.all_project_unit_ids:
                    ug = ctx.unit_grants_map.get((uid, r, u_id))
                    if ug:
                        ctx.revoke_grant(ug)
        else:
            target_units = ctx.resolve_user_target_units(uid)
            for u_id in target_units:
                for r in coding_roles:
                    ug = ctx.unit_grants_map.get((uid, r, u_id))
                    if ug:
                        ctx.revoke_grant(ug)


def _apply_cadre_defaults(ctx: ApplyContext) -> None:
    """Grant each user's home cadre default roles at the target units."""
    if ctx.project.project_structure_mode != "organization":
        raise OrganizationError("Cadre default roles apply to organization-mode projects.")
    # A placement edit names its own worker; the primary one may be
    # another placement of the same person (replace_placement_grants).
    override = ctx.payload.get("worker_id")
    for uid in ctx.target_user_uuids:
        worker = ctx.primary_worker_by_user.get(uid)
        if override is not None:
            worker = next((w for w in ctx.worker_rows if w.worker_id == override and w.is_active), None)
        if worker is None or worker.org_unit_id not in ctx.active_units:
            if len(ctx.target_user_uuids) == 1:
                raise OrganizationError("Selected user does not have an active worker placement in this project.")
            continue
        home_unit = ctx.active_units[worker.org_unit_id]
        lc = ctx.lc_by_pair.get((home_unit.org_level_id, worker.cadre_id))
        if lc is None or not lc.default_roles:
            if len(ctx.target_user_uuids) == 1:
                raise OrganizationError(
                    f"No default roles are configured for {worker.cadre.cadre_code!r} at {home_unit.level.level_name!r}."
                )
            continue
        target_units = (
            ctx.resolve_user_target_units(uid) if ctx.scope_mode != "project" else [home_unit.org_unit_id]
        )
        for r_str in lc.default_roles:
            r_enum = VaAccessRoles(r_str)
            for u_id in target_units:
                ctx.ensure_unit_grant(uid, r_enum, u_id)


def _apply_role_grant(ctx: ApplyContext) -> None:
    """Standard role grant (``_BULK_ROLE_MAP``): grant the roles, revoke the paired ones."""
    from app.services.org_grant_service import ROLES_ALLOWING_ORG_UNIT

    roles_to_grant, roles_to_revoke = _BULK_ROLE_MAP[ctx.operation]
    use_project_scope = (ctx.scope_mode == "project") or (ctx.operation == "project_pi")

    if not use_project_scope and ctx.project.project_structure_mode != "organization":
        raise OrganizationError(
            "Unit scopes require an organization-mode project; choose 'Project-wide' scope for sites-mode projects."
        )

    for uid in ctx.target_user_uuids:
        if use_project_scope:
            for r in roles_to_grant:
                ctx.ensure_project_grant(uid, r)
            for r_rev in roles_to_revoke:
                g_rev = ctx.proj_grants_map.get((uid, r_rev))
                if g_rev:
                    ctx.revoke_grant(g_rev)
        else:
            target_units = ctx.resolve_user_target_units(uid)
            target_set = set(target_units)
            for r in roles_to_grant:
                if r not in ROLES_ALLOWING_ORG_UNIT:
                    raise OrganizationError(f"Role {r.value!r} cannot be granted at unit scope.")
                for u_id in target_units:
                    ctx.ensure_unit_grant(uid, r, u_id)
                # When syncing scope (e.g. switching between Own unit, Cross-tree, All units at level, or Custom drawer),
                # deactivate active unit grants of the primary role outside target_set.
                if ctx.sync_scope and r == roles_to_grant[0]:
                    for u_id in ctx.all_project_unit_ids:
                        if u_id not in target_set:
                            ug = ctx.unit_grants_map.get((uid, r, u_id))
                            if ug and ug.grant_status == VaStatuses.active:
                                ctx.revoke_grant(ug)
            for r_rev in roles_to_revoke:
                for u_id in target_units:
                    ug_rev = ctx.unit_grants_map.get((uid, r_rev, u_id))
                    if ug_rev and ug_rev.grant_status == VaStatuses.active:
                        ctx.revoke_grant(ug_rev)


class _Stage(IntEnum):
    """How far an operation gets through the shared checks before its handler runs.

    Ordered: each stage runs every check of the stages below it. ``ACCOUNT`` runs
    before any preload; ``UNSCOPED`` after the preload but before the scope inputs
    are validated; ``REVOKE`` after them; ``GRANT`` also requires active users.
    """

    ACCOUNT = 0
    UNSCOPED = 1
    REVOKE = 2
    GRANT = 3


class _Operation(NamedTuple):
    handler: Callable[[ApplyContext], None]
    stage: _Stage


OPERATIONS: dict[str, _Operation] = {
    "activate_users": _Operation(_set_account_status, _Stage.ACCOUNT),
    "deactivate_users": _Operation(_set_account_status, _Stage.ACCOUNT),
    "revoke_all": _Operation(_revoke_all, _Stage.UNSCOPED),
    "revoke_pii": _Operation(_revoke_pii, _Stage.REVOKE),
    "revoke_coder": _Operation(_revoke_coder, _Stage.REVOKE),
    "cadre_defaults": _Operation(_apply_cadre_defaults, _Stage.GRANT),
    **{name: _Operation(_apply_role_grant, _Stage.GRANT) for name in _BULK_ROLE_MAP},
}
