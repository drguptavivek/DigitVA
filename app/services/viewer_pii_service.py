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
    MapMentorInstituteUser,
    MasMentorInstitute,
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)

# Roles that can contribute to PII visibility depending on tier and project mode
# (docs/policy/access-control-model.md, "The Three-Tier Mental Model & PII Boundary").
# Tier 3 (Health System Operations: org_unit scope, non-mentoring-institute) sees PII;
# Tier 1 (Project scope on tree projects) and Tier 2 (Mentoring Institute) are Non-PII.
_PII_GRANTING_ROLES = frozenset({
    VaAccessRoles.admin,
    VaAccessRoles.project_pi,
    VaAccessRoles.site_pi,
    VaAccessRoles.data_manager,
    VaAccessRoles.interview_supervisor,
    VaAccessRoles.coder,
    VaAccessRoles.coding_tester,
    VaAccessRoles.reviewer,
    VaAccessRoles.interviewer,
    VaAccessRoles.collaborator_pii,
})


def should_redact_pii(user, *, _grants=None) -> bool:
    """Return True if ``user`` must not see subject PII or staff identity.

    False (do not redact) when the user is an admin or holds a live PII-granting
    grant per ``ResolvedGrants.is_pii_grant`` (Tier 3 In-System unit grants on
    tree projects, or ``SITES_MODE_PII_ROLES`` on sites-only projects).
    Tier 1 (project-level roles on tree projects) and Tier 2 (Mentoring Institute
    members) return True (redacted).
    """
    # Imported here: app.services.authz imports this module at package load.
    from app.services.authz.grants import resolve_grants

    if not getattr(user, "user_id", None):
        return True
    resolved = _grants if _grants is not None else resolve_grants(user)
    if resolved.is_admin:
        return False
    return not any(
        resolved.is_pii_grant(g) for g in resolved.grants
    )


def pii_visible_user_ids(
    user_ids: Iterable[uuid.UUID], *, project_id: str | None = None
) -> set[uuid.UUID]:
    """The subset of *user_ids* for whom ``should_redact_pii`` is False, in one
    query: the people page asks it per person, never per row.

    Matches ``ResolvedGrants.is_pii_grant`` and the liveness rules of
    ``authz.grants._load_grants``. With *project_id* only grants that resolve
    to that project count (plus global admins).
    """
    # Imported here: app.services.authz imports this module at package load.
    from app.services.authz.grants import SITES_MODE_PII_ROLES, TIER3_UNIT_PII_ROLES
    from app.services.org_grant_service import active_project_condition

    ids = sorted(set(user_ids))
    if not ids:
        return set()
    grant = VaUserAccessGrants
    site = sa.orm.aliased(VaProjectSites, name="pii_grant_site")
    unit = sa.orm.aliased(MasOrgUnit, name="pii_grant_unit")
    level = sa.orm.aliased(MasOrgLevel, name="pii_grant_level")
    tree_unit = sa.orm.aliased(MasOrgUnit, name="pii_tree_unit")
    resolved_project = sa.func.coalesce(grant.project_id, site.project_id, unit.project_id)
    has_tree_cond = sa.exists(
        sa.select(1)
        .select_from(tree_unit)
        .where(
            tree_unit.project_id == resolved_project,
            tree_unit.is_active.is_(True),
        )
    )
    is_mentor_cond = sa.exists(
        sa.select(1)
        .select_from(MapMentorInstituteUser)
        .join(
            MasMentorInstitute,
            MasMentorInstitute.institute_id == MapMentorInstituteUser.institute_id,
        )
        .where(
            MapMentorInstituteUser.user_id == grant.user_id,
            MapMentorInstituteUser.is_active.is_(True),
            MasMentorInstitute.is_active.is_(True),
        )
    )
    live_scope_cond = sa.or_(
        sa.and_(grant.scope_type == VaAccessScopeTypes.project, grant.project_id.is_not(None)),
        sa.and_(grant.scope_type == VaAccessScopeTypes.project_site, site.project_site_id.is_not(None)),
        sa.and_(
            grant.scope_type == VaAccessScopeTypes.org_unit,
            unit.org_unit_id.is_not(None),
            level.org_level_id.is_not(None),
        ),
    )
    non_mentor_or_dm = sa.or_(~is_mentor_cond, grant.role == VaAccessRoles.data_manager)
    pii_grant_cond = sa.or_(
        grant.role.in_(
            (
                VaAccessRoles.admin,
                VaAccessRoles.collaborator_pii,
                VaAccessRoles.interviewer,
            )
        ),
        sa.and_(~has_tree_cond, non_mentor_or_dm, grant.role.in_(SITES_MODE_PII_ROLES)),
        sa.and_(
            has_tree_cond,
            grant.scope_type == VaAccessScopeTypes.org_unit,
            non_mentor_or_dm,
            grant.role.in_(TIER3_UNIT_PII_ROLES),
        ),
    )
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
        .outerjoin(level, sa.and_(
            level.org_level_id == unit.org_level_id,
            level.is_active.is_(True),
        ))
        .where(
            grant.user_id.in_(ids),
            grant.grant_status == VaStatuses.active,
            sa.or_(
                sa.and_(
                    grant.scope_type == VaAccessScopeTypes.global_scope,
                    grant.role == VaAccessRoles.admin,
                ),
                sa.and_(
                    resolved_project.is_not(None),
                    resolved_project == project_id if project_id is not None else sa.true(),
                    active_project_condition(resolved_project),
                    live_scope_cond,
                    pii_grant_cond,
                ),
            ),
        )
    ))
