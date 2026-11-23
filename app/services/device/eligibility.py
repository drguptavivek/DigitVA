"""Who may hold a device session and which projects may be a device's home
(docs/policy/mobile-sign-in.md). Part of ``device_auth_service``."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes, VaProjectMaster, VaStatuses, VaUsers
from app.services.authz import resolve_grants
from app.services.device.tokens import DeviceAuthError


def _project_active(project_id: str) -> bool:
    project = db.session.get(VaProjectMaster, project_id)
    return project is not None and project.project_status == VaStatuses.active


# Roles that may hold a device session without being an interviewer: the app
# also serves coding and review (docs/policy/field-data-collection.md).
_DEVICE_CODING_ROLES = frozenset(
    {VaAccessRoles.coder, VaAccessRoles.coding_tester, VaAccessRoles.reviewer}
)


def _native_grants(resolved):
    """The explicit grants besides interviewing and death register that open
    the app: coder, coding_tester or reviewer, and an ``interview_supervisor``
    unit grant (docs/policy/mobile-sign-in.md, "Interview supervisors on the
    phone"; supervision reaches through unit grants only). Gate open, never
    demo-training virtual. A supervisor grant on a project whose web intake is
    off does not count, as for an interviewer: there is nothing to supervise."""
    grants = [
        grant for grant in resolved.of(_DEVICE_CODING_ROLES | {VaAccessRoles.interview_supervisor}, virtual=False)
        if grant.opens_gate and (
            grant.role != VaAccessRoles.interview_supervisor or grant.scope_type == VaAccessScopeTypes.org_unit
        )
    ]
    supervised = {g.project_id for g in grants if g.role == VaAccessRoles.interview_supervisor}
    intake_off = set(db.session.scalars(
        sa.select(VaProjectMaster.project_id).where(
            VaProjectMaster.project_id.in_(supervised), VaProjectMaster.web_intake_mode == "off",
        )
    )) if supervised else set()
    for grant in grants:
        if grant.role != VaAccessRoles.interview_supervisor or grant.project_id not in intake_off:
            yield grant


def has_device_access(
    user: VaUsers,
    context: list[dict] | None = None,
    register_context: list[dict] | None = None,
    *,
    _grants=None,
) -> bool:
    """The sign-in, refresh and automatic-revocation grant check: the user
    may interview in at least one project (``interviewer_context``, which
    skips a project whose ``web_intake_mode`` is ``off``, so a session never
    opens with nothing to collect in), may register a death in one (a
    death_reporter, ``register_death_context``), or holds an explicit coder,
    coding_tester or reviewer grant whose gate is open, or an
    ``interview_supervisor`` unit grant (``_native_grants``). Demo-training
    virtual grants never count. Route authorization is separate: each route
    still checks its own role. The enrolment project is not required.

    *context* is the caller's already computed ``interviewer_context(user)`` and
    *register_context* their ``register_death_context(user, context)``, so
    neither is run twice."""
    from app.services.web_intake_service import interviewer_context, register_death_context

    if (interviewer_context(user) if context is None else context):
        return True
    resolved = _grants if _grants is not None else resolve_grants(user)
    if any(_native_grants(resolved)):
        return True
    return bool(register_death_context(user, []) if register_context is None else register_context)


def _native_grant_projects(resolved) -> set[str]:
    return {grant.project_id for grant in _native_grants(resolved)}


def _eligible_projects(context, register_context, resolved) -> list[dict]:
    ids = {e["project_id"] for e in context} | {e["project_id"] for e in register_context}
    ids |= _native_grant_projects(resolved)
    if not ids:
        return []
    rows = db.session.execute(
        sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name)
        .where(VaProjectMaster.project_id.in_(ids), VaProjectMaster.project_status == VaStatuses.active)
        .order_by(VaProjectMaster.project_id)
    ).all()
    return [{"project_id": r.project_id, "name": r.project_name} for r in rows]


def _default_home_project(context, register_context, resolved, eligible: list[dict]) -> str:
    """The home an app that sends no choice gets (old APKs): the lowest
    project id across interviewing and death register, else across native
    coding/review and supervision. Kept to the active *eligible* projects when there are any,
    so the default is always one the picker lists."""
    pool = {e["project_id"] for e in context + register_context} or _native_grant_projects(resolved)
    active = {p["project_id"] for p in eligible}
    if active:
        pool = (pool & active) or active
    return min(pool)


def eligible_device_projects(user: VaUsers) -> list[dict]:
    """Every active project *user* may make a device's home
    (docs/policy/mobile-sign-in.md, home project): interviewing, death
    register, native coding/review or supervision. ``[{project_id, name}]`` sorted by id;
    the app asks the user to pick when there is more than one."""
    from app.services.web_intake_service import interviewer_context, register_death_context

    resolved = resolve_grants(user)
    context = interviewer_context(user, _grants=resolved)
    return _eligible_projects(context, register_death_context(user, context, _grants=resolved), resolved)


def _no_access_error(user: VaUsers, resolved=None) -> DeviceAuthError:
    """The refusal for a user without device access. An interviewer grant on an
    active project whose web intake is off gets ``project_intake_off`` so the
    user and their supervisor know collection is switched off, not that the
    account has no grants (same 403 and shape; old APKs show their generic
    error). Anyone else keeps ``no_interviewer_grant``."""
    resolved = resolved if resolved is not None else resolve_grants(user)
    project_ids = {g.project_id for g in resolved.of({VaAccessRoles.interviewer}, virtual=False)}
    if project_ids and db.session.scalar(
        sa.select(sa.exists().where(
            VaProjectMaster.project_id.in_(project_ids),
            VaProjectMaster.project_status == VaStatuses.active,
            VaProjectMaster.web_intake_mode == "off",
        ))
    ):
        return DeviceAuthError(
            "Data collection is switched off for your project. Ask your project administrator.",
            "project_intake_off", 403,
        )
    return DeviceAuthError("You have no access in any project.", "no_interviewer_grant", 403)
