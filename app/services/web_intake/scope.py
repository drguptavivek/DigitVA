"""Project mode and interviewer scope, unique ids, unit context and the worklist scope helpers.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaUsers,
    VaWebIntakeDraft,
)
from app.models.va_web_intake import (
    DEATH_NUMBER_SEQUENCE,
)
from app.services import (
    org_grant_service,
    training_scope,
)
from app.services import organization_service as org
from app.services.authz import resolve_grants, subtree_select
from app.services.authz.actions import DEATH_REGISTERING_ROLES
from app.services.authz.consulted import mark_consulted
from app.services.case_transition_service import WebIntakeError
from app.services.duplicate_exclusion import EXCLUDED_HOLDS
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    consent_is_valid,
)
from app.services.web_intake import facade


def get_web_intake_mode(project_id: str) -> str:
    project = db.session.get(VaProjectMaster, project_id)
    if project is None or project.project_status != VaStatuses.active:
        return "off"
    return project.web_intake_mode or "off"


def _mode_allows(mode: str, *, death_register: bool) -> bool:
    if mode == "both":
        return True
    return mode == ("death_register" if death_register else "direct")


_INTERVIEWER = frozenset({VaAccessRoles.interviewer})


_DEATH_REPORTER = frozenset({VaAccessRoles.death_reporter})


def interviewer_context(
    user: VaUsers,
    roles: frozenset = _INTERVIEWER,
    *,
    _grants=None,
) -> list[dict]:
    """Projects and sites where this user may fill questionnaires.

    One entry per (project, site) reachable through interviewer grants at
    project, project-site or organization-unit scope, for projects whose
    web intake is switched on. Unit grants list the units the interviewer
    belongs to so drafts and deaths can be attributed to a unit.

    *roles* names the grants the reach is built from. The default, interviewer
    alone, is every interviewing surface; the register routes pass
    ``DEATH_REGISTERING_ROLES`` (``register_death_context``), and a
    ``death_reporter``'s own reach is built from that role alone
    (``_DEATH_REPORTER``), so neither role widens the other's.
    """
    resolved = _grants if _grants is not None else resolve_grants(user)
    grants = list(resolved.of(roles, virtual=False))
    pairs: dict[tuple[str, str], dict] = {}

    # Project and project-site grants: the sites of the project's active
    # forms (a site grant only its own site).
    wide = [
        sa.and_(VaForms.project_id == g.project_id,
                VaForms.site_id == g.site_id if g.site_id else sa.true())
        for g in grants if g.is_wide
    ]
    if wide:
        rows = db.session.execute(
            sa.select(VaForms.project_id, VaForms.site_id)
            .where(VaForms.form_status == VaStatuses.active, sa.or_(*wide))
            .distinct()
        ).all()
        for project_id, site_id in rows:
            pairs[(project_id, site_id)] = {"org_units": []}

    # A pair a wide grant reaches keeps ``org_units: []``, the whole tree, as
    # ``reachable_unit_ids`` has it: a unit grant there narrows nothing.
    whole_tree = set(pairs)

    # Unit grants: every active site of the unit's project.
    unit_grants = [g for g in grants if not g.is_wide]
    if unit_grants:
        units = {
            u.org_unit_id: u
            for u in db.session.scalars(
                sa.select(MasOrgUnit).where(
                    MasOrgUnit.org_unit_id.in_({g.org_unit_id for g in unit_grants})
                )
            )
        }
        site_ids_by_project: dict[str, list[str]] = {}
        for project_id, site_id in db.session.execute(
            sa.select(VaProjectSites.project_id, VaProjectSites.site_id)
            .where(
                VaProjectSites.project_id.in_({g.project_id for g in unit_grants}),
                VaProjectSites.project_site_status == VaStatuses.active,
            )
            .order_by(VaProjectSites.site_id)
        ):
            site_ids_by_project.setdefault(project_id, []).append(site_id)
        for grant in unit_grants:
            unit = units.get(grant.org_unit_id)
            if unit is None:
                continue
            for site_id in site_ids_by_project.get(grant.project_id, ()):
                if (grant.project_id, site_id) in whole_tree:
                    continue
                entry = pairs.setdefault((grant.project_id, site_id), {"org_units": []})
                unit_id_str = str(unit.org_unit_id)
                if any(u["org_unit_id"] == unit_id_str for u in entry["org_units"]):
                    continue
                entry["org_units"].append(
                    {
                        "org_unit_id": unit_id_str,
                        "unit_code": unit.unit_code,
                        "unit_name": unit.unit_name,
                        "path": str(unit.path),
                    }
                )

    if not pairs:
        return []
    project_ids = {p for p, _ in pairs}
    site_ids = {s for _, s in pairs}
    active_pair_rows = db.session.execute(
        sa.select(
            VaProjectSites.project_id,
            VaProjectSites.site_id,
            VaProjectMaster.project_name,
            VaProjectMaster.web_intake_mode,
            VaSiteMaster.site_name,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_id.in_(project_ids),
            VaProjectSites.site_id.in_(site_ids),
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
        )
    ).all()
    info_by_pair = {(r.project_id, r.site_id): r for r in active_pair_rows}

    context = []
    for (project_id, site_id), entry in sorted(pairs.items()):
        info = info_by_pair.get((project_id, site_id))
        if info is None:
            continue
        mode = info.web_intake_mode or "off"
        if mode == "off":
            continue
        context.append(
            {
                "project_id": project_id,
                "project_name": info.project_name,
                "site_id": site_id,
                "site_name": info.site_name if info.site_name else site_id,
                "web_intake_mode": mode,
                "org_units": entry["org_units"],
            }
        )
    return context


def register_death_context(
    user: VaUsers,
    interview_context: list[dict] | None = None,
    *,
    _grants=None,
) -> list[dict]:
    """The ``interviewer_context`` entries where *user* may register a death:
    reached through an interviewer or death_reporter grant, in a project
    whose ``web_intake_mode`` keeps a death register. The one predicate of the
    register routes (``register_death`` checks scope through the same
    ``_require_scope``), ``/me/access`` ``actions.register_death`` and the
    app's sign-in check. *interview_context*: the caller's already computed
    ``interviewer_context(user)``, reused when they hold no death_reporter
    grant (then it is the whole answer)."""
    resolved = _grants if _grants is not None else resolve_grants(user)
    if interview_context is not None and not any(resolved.of(_DEATH_REPORTER, virtual=False)):
        entries = interview_context
    else:
        entries = facade().interviewer_context(user, DEATH_REGISTERING_ROLES, _grants=resolved)
    return [e for e in entries if _mode_allows(e["web_intake_mode"], death_register=True)]


def self_coding_project_ids(user: VaUsers, *, _grants=None) -> frozenset[str]:
    """Projects where *user* may be offered "Code this case now": a self-coding
    project in which they hold a coder grant that codes (gate open, coding
    scope level met). Plus the training project while the user self-codes in
    a self-coding training session (``training_self_coding_ids``, one memoised
    query); there only on those slot units (``can_code_now``, ``_code_now``).
    The action itself re-checks scope and ownership
    (``coder_workflow_service.allocate_own_case``)."""
    from app.services import training_demo_service

    resolved = _grants if _grants is not None else resolve_grants(user)
    projects = {
        g.project_id
        for g in resolved.of({VaAccessRoles.coder}, virtual=False)
        if g.opens_gate
        and (settings := resolved.projects.get(g.project_id)) is not None
        and settings.self_coding
        and resolved.codes(g)
    }
    if training_demo_service.training_self_coding_ids(user.user_id):
        projects.add(training_demo_service.TRAINING_PROJECT_ID)
    return frozenset(projects)


def _code_now_unit_ok(user: VaUsers, project_id: str, org_unit_id) -> bool:
    """In the training project "Code this case now" holds only on the user's
    self-coding slot units; elsewhere the project decides (N6)."""
    from app.services import training_demo_service

    if project_id != training_demo_service.TRAINING_PROJECT_ID:
        return True
    return org_unit_id in training_demo_service.training_self_coding_ids(user.user_id)


def can_code_now(user: VaUsers, draft: VaWebIntakeDraft) -> bool:
    """Whether the reply to *user*'s submit of *draft* offers "Code this case
    now": a submitted, completed interview that entered coding (consent valid)
    in a self-coding project where the user codes. The case is usually still
    waiting for attachments or SmartVA; the action answers 409 ``not_ready``
    until it is ready."""
    return (
        draft.status == "submitted"
        and draft.va_sid is not None
        and (draft.meta or {}).get("interviewOutcome") == "completed"
        and draft.collection_hold not in EXCLUDED_HOLDS
        and draft.project_id in self_coding_project_ids(user)
        and (submission := db.session.get(VaSubmissions, draft.va_sid)) is not None
        and _code_now_unit_ok(user, draft.project_id, submission.org_unit_id)
        and consent_is_valid(submission.va_consent)
    )


def reachable_unit_ids(user: VaUsers, project_id: str, site_id: str | None = None,
                       roles: frozenset = _INTERVIEWER) -> set[uuid.UUID] | None:
    """Active units of *project_id* this interviewer may attribute an entry to.

    The unit-picking half of the rule ``_worklist_scope`` applies to cases
    (docs/policy/web-intake.md, "Who sees which cases"), built from the same
    ``resolve_grants`` data. ``None`` means the whole tree: a project grant
    on the project, or a site grant on exactly (*project_id*, *site_id*).
    Otherwise the subtrees of the user's interviewer unit grants in this
    project (an empty set reaches nothing). A site grant on another site
    widens nothing here.

    With ``site_id=None`` (the per-project picker, which has no site: device
    ``/units`` and ``prefill_policy``) a wide grant on *any* site of the
    project returns ``None``: the picker offers every unit some site of the
    project allows, and the create-time check (``_require_scope``, which
    passes its site) still holds each site to its own grants.

    No admin or project_pi bypass: web intake is strictly grant-based. *roles*
    as ``interviewer_context``.
    """
    mark_consulted()
    units: set[uuid.UUID] = set()
    for grant in resolve_grants(user).of(roles, virtual=False):
        if grant.project_id != project_id:
            continue
        if not grant.is_wide:
            units.add(grant.org_unit_id)
        elif site_id is None or grant.site_id in (None, site_id):  # site_id None: project grant
            return None
    if not units:
        return set()
    return set(db.session.scalars(subtree_select(units)))


def _require_scope(user: VaUsers, project_id: str, site_id: str, org_unit_id: object | None,
                   roles: frozenset = _INTERVIEWER, *, entries: list[dict] | None = None,
                   unrouted_ok: bool = False) -> dict:
    """Return the context entry for (project, site) or raise 403.

    In a project with an organization tree, a unit must always be named,
    whatever the grant's scope — the routed unit is what makes a submission
    codeable at all (docs/policy/organization-model.md phase 4), and an
    unrouted one is invisible to every coder. A project- or site-scoped
    interviewer grant on this project-site may name *any* active unit of
    the project; a unit-scoped grant is held to its own subtree
    (``reachable_unit_ids``). A project with no tree
    keeps the pre-phase-4 behaviour: no unit is required. *roles* as
    ``interviewer_context``: the grants whose reach is checked. *entries*: the
    caller's own ``interviewer_context(user, roles)`` of this request, reused
    instead of rebuilt; the checks are the same. *unrouted_ok*: a Collect Plus
    standalone push whose org code matched no unit it may name may start
    without one; routing then leaves it to the mapping fallback or the
    project's unrouted queue (offline-api-contract.md section 17).
    """
    entry = None
    # A context built for other roles is never reused: the role set decides reach.
    reuse = entries is not None and roles == _INTERVIEWER
    for candidate in (entries if reuse else facade().interviewer_context(user, roles)):
        if candidate["project_id"] == project_id and candidate["site_id"] == site_id:
            entry = candidate
            break
    if entry is None:
        raise WebIntakeError("You do not have access to that project and site.", 403)

    has_tree = project_id in org_grant_service.projects_with_org_tree({project_id})
    if not has_tree:
        if org_unit_id:
            allowed = {u["org_unit_id"] for u in entry["org_units"]}
            if str(org_unit_id) not in allowed:
                raise WebIntakeError("You are not attached to that organization unit.", 403)
        elif entry["org_units"]:
            raise WebIntakeError("Choose the organization unit for this entry.", 400)
        return entry

    if not org_unit_id:
        if unrouted_ok:
            return entry
        raise WebIntakeError("Choose the organization unit for this entry.", 400)
    try:
        unit_id = uuid.UUID(str(org_unit_id))
    except (ValueError, TypeError, AttributeError):
        raise WebIntakeError("Invalid organization unit.", 400) from None

    reachable = reachable_unit_ids(user, project_id, site_id, roles)
    if reachable is not None and unit_id not in reachable:
        raise WebIntakeError("That organization unit is outside what you may access.", 403)

    unit = db.session.get(MasOrgUnit, unit_id)
    if unit is None or unit.project_id != project_id or not unit.is_active:
        raise WebIntakeError("That organization unit is not active in this project.", 400)

    return entry


def _allocate_unique_id(prefix: str) -> tuple[int, str]:
    number = db.session.execute(sa.text(f"SELECT nextval('{DEATH_NUMBER_SEQUENCE}')")).scalar_one()
    return int(number), f"{prefix}-{int(number):06d}"


def _unit_context(org_unit_id: object | None) -> dict:
    """Ancestor codes of a unit keyed by level: {"org_<level>_code": code, ...}."""
    if not org_unit_id:
        return {}
    unit = db.session.get(MasOrgUnit, uuid.UUID(str(org_unit_id)))
    if unit is None:
        return {}
    codes = str(unit.path).split(".")
    # Routing attributes a submission to the deepest code naming a *live*
    # unit, so a deactivated ancestor's code would be inert at best and
    # misleading in the stored payload -- keep the active-only default.
    rows = org.list_units_by_codes(unit.project_id, codes)
    context: dict = {}
    for row in rows:
        context[f"org_{row['level_code']}_code"] = row["unit_code"]
        context[f"org_{row['level_code']}_name"] = row["unit_name"]
    return context


def _unit_label(unit: MasOrgUnit | None) -> str:
    """The unit's own code and name, e.g. "PHC06 PHC name 2" (Id10055's
    prefill, owner decision 2026-10-23); "" without a unit."""
    return f"{unit.unit_code} {unit.unit_name}" if unit is not None else ""


def _unit_prefill_parts(unit_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[dict, str]]:
    """``{unit_id: (Id10002/Id10003 presets, unit label)}`` for
    ``_prefill_from_death``'s ``unit_parts``, in two queries for any number
    of units (units, presets)."""
    if not unit_ids:
        return {}
    units = db.session.scalars(
        sa.select(MasOrgUnit).where(MasOrgUnit.org_unit_id.in_(sorted(unit_ids)))
    ).all()
    presets = org_grant_service.resolve_unit_va_presets(sorted(unit_ids))
    parts = {}
    for unit in units:
        parts[unit.org_unit_id] = (
            {
                org_grant_service.VA_PRESET_QUESTION_NAMES[column]: entry["value"]
                for column, entry in presets.get(unit.org_unit_id, {}).items()
            },
            _unit_label(unit),
        )
    return parts


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _encode_cursor(updated_at: datetime, death_id: uuid.UUID) -> str:
    micros = (updated_at - _EPOCH) // timedelta(microseconds=1)
    return f"{micros}_{death_id}"


def _decode_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    try:
        micros, death_id = raw.split("_", 1)
        return _EPOCH + timedelta(microseconds=int(micros)), uuid.UUID(death_id)
    except (ValueError, OverflowError):
        raise WebIntakeError("Invalid cursor.") from None


def _assigned_only(resolved):
    """*resolved* without the grants a coder's self-coding project implies
    (``source == "self_coding"``): the grant rows someone actually assigned."""
    return dataclasses.replace(resolved, grants=tuple(g for g in resolved.grants if g.source == "assigned"))


def _worklist_scope(user: VaUsers, context: list[dict] | None = None, roles: frozenset = _INTERVIEWER,
                    *, assigned_only: bool = False):
    """SQL condition for the cases this interviewer's grants reach, or None.

    Per project-site of ``interviewer_context`` (*context* when the caller
    already has it): a project grant, or a site grant on that very site,
    sees the whole project-site; otherwise the subtrees of the user's unit
    grants in that project (a case with no unit is outside every subtree).
    A wider grant wins over a unit grant on the same project-site
    (docs/policy/web-intake.md, "Who sees which cases"). The subtrees stay
    sub-selects, so the grants cost one memoised lookup however many
    project-sites there are. *roles* as ``interviewer_context`` (*context*
    must then be built from the same roles). *assigned_only* leaves out the
    interviewer grant a self-coding coder is implied (``source ==
    "self_coding"``): the reach that confers registration-number rights, which
    a coding role never does (policy decisions 11 and 14).
    """
    wide: set[tuple[str, str | None]] = set()
    unit_grants: dict[str, set[uuid.UUID]] = {}
    resolved = resolve_grants(user)
    if assigned_only:
        resolved = _assigned_only(resolved)
    for grant in resolved.of(roles, virtual=False):
        if grant.is_wide:
            wide.add((grant.project_id, grant.site_id))  # site_id None: project grant
        else:
            unit_grants.setdefault(grant.project_id, set()).add(grant.org_unit_id)
    conditions = []
    for entry in facade().interviewer_context(user, roles, _grants=resolved) if context is None else context:
        project_id, site_id = entry["project_id"], entry["site_id"]
        pair = sa.and_(VaDeathRegister.project_id == project_id, VaDeathRegister.site_id == site_id)
        if (project_id, None) not in wide and (project_id, site_id) not in wide:
            units = unit_grants.get(project_id)
            if not units:
                continue
            pair = sa.and_(pair, VaDeathRegister.org_unit_id.in_(subtree_select(units)))
        conditions.append(pair)
    if not conditions:
        return None
    return sa.and_(
        sa.or_(*conditions),
        # "Details pending" only for its starter; supervisors see it in
        # list_supervised_cases.
        sa.or_(
            VaDeathRegister.status != "draft_identity",
            VaDeathRegister.started_by_user_id == user.user_id,
        ),
        # A public-demo account sees only the deaths it registered
        # (docs/policy/public-demo.md section 3), as get_death.
        *([VaDeathRegister.registered_by == user.user_id] if user.is_public_demo else []),
        # The Expo training scope: one funnel for the worklist, the register
        # lists and the Home counts (docs/policy/training-demo-project.md).
        *training_scope.conditions(VaDeathRegister.project_id),
    )
