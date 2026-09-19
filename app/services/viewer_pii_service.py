"""Viewer PII redaction — the single decision point for whether the
current viewer's read-only access must hide personal data.

Policy: docs/policy/access-control-model.md ("collaborator",
"collaborator_pii", "Why this is a role and not a flag").
Task record: .tasks/viewer-pii-roles.md.

Rule (decided, not re-litigated here): redact ONLY for a user whose read
access comes through a plain ``collaborator`` grant and who holds no other
active grant that would grant personal data. Every other role — admin,
project_pi, site_pi, data_manager, coder, coding_tester, reviewer,
interviewer, collaborator_pii — sees personal data exactly as it does today.
A user holding both ``collaborator`` and, say, ``coder`` sees personal data
via the coder grant.

Call ``should_redact_pii`` wherever a screen decides whether to show subject
PII (payload fields flagged ``is_pii``) or staff identity (who collected,
coded, reviewed a death). Never re-implement this check per screen: a screen
that checks only "is this read-only" and forgets this call fails OPEN (a
plain viewer sees personal data), which is the failure mode that matters.
"""

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
from app.services.org_grant_service import active_project_condition

# Every role except plain `collaborator` already sees personal data today.
# Holding any ONE of these as an active grant unlocks personal data for the
# viewer, even if the same user also holds a plain collaborator grant.
_PII_GRANTING_ROLES = frozenset(VaAccessRoles) - {VaAccessRoles.collaborator}


def should_redact_pii(user) -> bool:
    """Return True if ``user`` must not see subject PII or staff identity.

    False (do not redact) for every role except a user whose active grants
    are exclusively plain ``collaborator``. A user with no active grants at
    all also gets True: this helper only governs what a read-only view may
    display once access has already been granted elsewhere — it is not an
    access check.
    """
    user_id = getattr(user, "user_id", None)
    if not user_id:
        return True

    # A PII-granting grant only counts while its project is active. The
    # access resolvers all apply active_project_condition, so a closed
    # project's grants no longer open any screen; if this check ignored the
    # project's status, that same dormant grant would still switch redaction
    # off on the screens the user reaches through an open project's plain
    # collaborator grant. The grant names its project differently per scope,
    # so resolve it per scope; a global grant (admin) has no project and
    # counts unconditionally.
    grant_project_id = sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id,
        ),
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            sa.select(VaProjectSites.project_id)
            .where(VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id)
            .correlate(VaUserAccessGrants)
            .scalar_subquery(),
        ),
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            sa.select(MasOrgUnit.project_id)
            .where(MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
            .correlate(VaUserAccessGrants)
            .scalar_subquery(),
        ),
    )
    stmt = sa.select(
        sa.exists().where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.role.in_(_PII_GRANTING_ROLES),
            VaUserAccessGrants.grant_status == VaStatuses.active,
            sa.or_(
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
                active_project_condition(grant_project_id),
            ),
        )
    )
    return not bool(db.session.scalar(stmt))
