"""Viewer PII redaction — the single decision point for whether the
current viewer's read-only access must hide personal data.

Policy: docs/policy/access-control-model.md ("collaborator",
"collaborator_pii", "Why this is a role and not a flag").
Task record: .tasks/viewer-pii-roles.md.

Rule (decided, not re-litigated here): redact unless the user holds a live
grant in ``_PII_GRANTING_ROLES`` — admin, project_pi, site_pi, data_manager,
coder, coding_tester, reviewer, interviewer, collaborator_pii. A plain
``collaborator`` and an ``interview_supervisor`` (docs/policy/web-intake.md,
"Privacy rule (item 14)") are redacted.
A user holding both ``collaborator`` and, say, ``coder`` sees personal data
via the coder grant.

Call ``should_redact_pii`` wherever a screen decides whether to show subject
PII (payload fields flagged ``is_pii``) or staff identity (who collected,
coded, reviewed a death). Never re-implement this check per screen: a screen
that checks only "is this read-only" and forgets this call fails OPEN (a
plain viewer sees personal data), which is the failure mode that matters.
"""

import uuid
from collections.abc import Iterable

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)

# An explicit allowlist, so a role added later redacts until someone decides
# otherwise (a deny-list fails open). Membership per
# docs/policy/access-control-model.md: project_pi and the In-charge (site_pi)
# see every screen "with personal data"; collaborator_pii exists to see it.
# The rollout note under "collaborator" narrowed only that role, so admin,
# data_manager, coder, coding_tester, reviewer and interviewer keep the
# personal data they saw before the viewer split. Left out: collaborator
# (redacted by definition) and interview_supervisor, whose identifier access
# is confined to the intake worklist and case views (docs/policy/web-intake.md,
# "Privacy rule (item 14)") and never lifts this redaction.
_PII_GRANTING_ROLES = frozenset({
    VaAccessRoles.admin,
    VaAccessRoles.project_pi,
    VaAccessRoles.site_pi,
    VaAccessRoles.data_manager,
    VaAccessRoles.coder,
    VaAccessRoles.coding_tester,
    VaAccessRoles.reviewer,
    VaAccessRoles.interviewer,
    VaAccessRoles.collaborator_pii,
})


def should_redact_pii(user) -> bool:
    """Return True if ``user`` must not see subject PII or staff identity.

    False (do not redact) when the user holds a live grant in
    ``_PII_GRANTING_ROLES``. A user with no such grant, or no grants at all,
    gets True: this helper only governs what a read-only view may display
    once access has already been granted elsewhere — it is not an access
    check.

    "Live" is the authz grant relation (``resolve_grants``): an active grant
    on an active project, and for a pair or unit grant an active pair or
    unit. Reusing it keeps redaction in step with the resolvers, so a grant
    that opens no screen (closed project, deactivated unit or pair) cannot
    switch redaction off on screens reached through another grant.
    Demo-training virtual grants are ignored: they are derived, not held.
    """
    # Imported here: app.services.authz imports this module at package load.
    from app.services.authz.grants import resolve_grants

    if not getattr(user, "user_id", None):
        return True
    resolved = resolve_grants(user)
    if resolved.is_admin:
        return False
    return not any(
        g.role in _PII_GRANTING_ROLES and not g.virtual for g in resolved.grants
    )


def pii_visible_user_ids(
    user_ids: Iterable[uuid.UUID], *, project_id: str | None = None
) -> set[uuid.UUID]:
    """The subset of *user_ids* for whom ``should_redact_pii`` is False, in one
    query: the people page asks it per person, never per row.

    Same role set (``_PII_GRANTING_ROLES``) and the same liveness as
    ``authz.grants._load_grants``: an active grant on an active project, and
    for a unit or pair grant an active unit or pair; a global grant counts
    only as ``admin``. Demo-training virtual grants are never rows, so they
    cannot count here either. tests/test_people_roles.py pins the parity.

    With *project_id* only grants that resolve to that project count (the
    people page asks "in this project"); a global admin still counts, as
    ``should_redact_pii`` is False for an admin everywhere.
    """
    # Imported here: app.services.authz imports this module at package load.
    from app.services.org_grant_service import active_project_condition

    ids = sorted(set(user_ids))
    if not ids:
        return set()
    grant = VaUserAccessGrants
    site = sa.orm.aliased(VaProjectSites, name="pii_grant_site")
    unit = sa.orm.aliased(MasOrgUnit, name="pii_grant_unit")
    resolved_project = sa.func.coalesce(grant.project_id, site.project_id, unit.project_id)
    return set(db.session.scalars(
        sa.select(grant.user_id)
        .distinct()
        .select_from(grant)
        .outerjoin(site, sa.and_(
            site.project_site_id == grant.project_site_id,
            site.project_site_status == VaStatuses.active,
        ))
        .outerjoin(unit, sa.and_(
            unit.org_unit_id == grant.org_unit_id,
            unit.is_active.is_(True),
        ))
        .where(
            grant.user_id.in_(ids),
            grant.grant_status == VaStatuses.active,
            grant.role.in_(_PII_GRANTING_ROLES),
            sa.or_(
                sa.and_(
                    grant.scope_type == VaAccessScopeTypes.global_scope,
                    grant.role == VaAccessRoles.admin,
                ),
                sa.and_(
                    resolved_project.is_not(None),
                    resolved_project == project_id if project_id is not None else sa.true(),
                    active_project_condition(resolved_project),
                ),
            ),
        )
    ))
